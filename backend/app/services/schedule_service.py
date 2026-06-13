"""ScheduleService：调度子系统用例编排。

- dispatch / try_auto_dispatch：系统自动叫号（E_chargingRequest/End_Charging/runPile 等触发）
- handle_fault：故障再调度（优先级 / 时间顺序），骨架=「暂停叫号 → 重排 → 恢复叫号」
- handle_recovery：故障恢复后趁机整体重排
- single_dispatch / batch_dispatch：Bonus 单次/批量调度总充电时长最短（委托 Scheduler 求解）
"""
from __future__ import annotations

from typing import List, Optional

from ..domain.enums import BusinessError, ChargeMode, PileStatus, RequestStatus
from ..domain.models import ChargingRequest, ChargingStation, FaultRecord
from ..domain.scheduler import Scheduler


class ScheduleService:
    def __init__(self, station: ChargingStation, scheduler: Scheduler, clock,
                 config, billing_service, request_repo, fault_repo):
        self.station = station
        self.scheduler = scheduler
        self.clock = clock
        self.config = config
        self.billing_service = billing_service
        self.request_repo = request_repo
        self.fault_repo = fault_repo
        self.dispatch_paused = False
        self._fault_seq = 0

    # ---- 叫号暂停/恢复（故障调度的事务边界）----
    def pause_waiting_area_dispatch(self) -> None:
        self.dispatch_paused = True

    def resume_waiting_area_dispatch(self) -> None:
        self.dispatch_paused = False
        self.try_auto_dispatch()

    # ---- 自动叫号 ----
    def try_auto_dispatch(self) -> List[dict]:
        """引擎每个 tick 与各资源变动事件后调用，幂等。"""
        if self.dispatch_paused:
            return []
        if self.config.dispatchMode == "batch_optimal":
            return self.batch_dispatch() or []
        moved: List[dict] = []
        for mode in (ChargeMode.FAST, ChargeMode.TRICKLE):
            moved += self.dispatch(mode)
        return moved

    def dispatch(self, mode: ChargeMode) -> List[dict]:
        """按进入等候区先后从对应模式等待队列调入车辆，分配(等待+充电)最短的桩。"""
        if self.dispatch_paused:
            return []
        if self.config.dispatchMode == "batch_optimal":
            # 批量模式：仅当 等候区车数==空位总数 时整批最优调度（设计 Alt[m==n]）
            return self.batch_dispatch() or []
        if self.config.dispatchMode == "single_optimal":
            return self.single_dispatch(mode)
        moved: List[dict] = []
        wa = self.station.waiting_area
        queue = wa.get_queue(mode)
        now = self.clock.now()
        while True:
            head = queue.peek()
            if head is None:
                break
            pile = self.scheduler.assign_pile(head, self.station.charging_area.get_all_piles(), now)
            if pile is None:
                break
            wa.remove(head)
            self._place(head, pile)
            moved.append({"carId": head.car_id, "to": pile.pile_id})
        return moved

    def _place(self, cr: ChargingRequest, pile) -> None:
        pile.add_to_queue(cr)
        cr.status = RequestStatus.QUEUING
        self.request_repo.save(cr)

    # ---- Bonus 19：单次调度总充电时长最短 ----
    def single_dispatch(self, mode: ChargeMode) -> List[dict]:
        """同时空出 k 个车位时，对队首 k 辆车枚举分配方案使总时长最短。"""
        area, wa = self.station.charging_area, self.station.waiting_area
        now = self.clock.now()
        free_piles = area.get_free_piles(mode)
        k = min(sum(p.queue.free_spots() for p in free_piles), wa.get_queue(mode).size())
        if k <= 0:
            return []
        cars = wa.peek_n(mode, k)
        plan = self.scheduler.min_total_time_assign(free_piles, cars, now)
        if plan is None:  # 规模超限等情况退回默认贪心
            return self._greedy_fallback(mode)
        moved = []
        for car, pile in plan:
            wa.remove(car)
            self._place(car, pile)
            moved.append({"carId": car.car_id, "to": pile.pile_id})
        return moved

    # ---- Bonus 20：批量调度总充电时长最短 ----
    def batch_dispatch(self) -> Optional[List[dict]]:
        """触发条件：等候区车辆数 == 全部充电桩空位总数（Alt[m==n] 才进入）。"""
        area, wa = self.station.charging_area, self.station.waiting_area
        now = self.clock.now()
        m = wa.get_total_waiting_count()
        n = area.get_all_free_spots()
        if m == 0 or m != n:
            return None
        piles = [p for p in area.get_all_piles() if p.is_dispatchable()]
        cars = wa.get_all_requests()
        plan = self.scheduler.min_total_time_assign(piles, cars, now)
        if plan is None:  # 不存在满足同模式约束的完整方案（全部记 ∞）
            return None
        moved = []
        for car, pile in plan:
            wa.remove(car)
            self._place(car, pile)
            moved.append({"carId": car.car_id, "to": pile.pile_id})
        return moved

    def _greedy_fallback(self, mode: ChargeMode) -> List[dict]:
        moved: List[dict] = []
        wa = self.station.waiting_area
        queue = wa.get_queue(mode)
        now = self.clock.now()
        while True:
            head = queue.peek()
            if head is None:
                break
            pile = self.scheduler.assign_pile(head, self.station.charging_area.get_all_piles(), now)
            if pile is None:
                break
            wa.remove(head)
            self._place(head, pile)
            moved.append({"carId": head.car_id, "to": pile.pile_id})
        return moved

    # ---- 故障调度（系统事件 reportFault）----
    def handle_fault(self, pile_id: str, fault_type: str = "设备故障",
                     strategy: Optional[str] = None) -> FaultRecord:
        pile = self.station.find_pile(pile_id)
        if pile.status is PileStatus.FAULT:
            raise BusinessError(f"{pile_id} 已处于故障状态")
        if pile.status is not PileStatus.RUNNING:
            raise BusinessError(f"{pile_id} 未在运行，无需故障调度")
        strategy = strategy or self.config.faultStrategy
        if strategy not in ("priority", "time_order"):
            raise BusinessError(f"未知调度策略: {strategy}")
        now = self.clock.now()

        # (1) 坏桩置“故障”+ 建故障档案
        pile.status = PileStatus.FAULT
        pile.accept_new_request = False
        self._fault_seq += 1
        rec = FaultRecord(f"FLT{now.strftime('%Y%m%d%H%M%S')}-{self._fault_seq:03d}",
                          pile_id, fault_type, strategy, now)

        # (2) 暂停等候区叫号：把好桩空位锁给受灾车
        # try/finally 保证即使重排途中异常也必定恢复叫号，避免 dispatch_paused 永久卡死、新车永不被叫号
        self.pause_waiting_area_dispatch()
        try:
            victims: List[ChargingRequest] = []
            # (3) 充电中车辆：按已充电量部分计费
            crc = pile.queue.get_charging_request()
            if crc:
                self.billing_service.partial_settle(crc, pile, now)
                duration = ((now - crc.charging_start_time).total_seconds() / 3600.0
                            if crc.charging_start_time else 0.0)
                pile.record_finished(crc.actual_amount or 0.0, duration)
                pile.remove_from_queue(crc)
                rec.interrupted.append(crc.car_id)
                remaining = crc.requested_amount - (crc.actual_amount or 0.0)
                if self.config.interruptPolicy == "requeue" and remaining > 1e-6:
                    # 可选策略：剩余电量重新入队，受灾车最高优先
                    crc.requested_amount = round(remaining, 4)
                    crc.status = RequestStatus.WAITING
                    crc.pile_id = None
                    crc.charging_start_time = None
                    crc.actual_amount = None
                    crc.end_time = None
                    victims.append(crc)
                else:
                    # 概要设计：置“已中断”，由用户重新申请
                    crc.status = RequestStatus.INTERRUPTED
                    self.station.release_active(crc)
                self.request_repo.save(crc)

            # (4) 排队车辆登记并取出
            queued = pile.queue.get_queuing_cars()
            for cr in queued:
                pile.remove_from_queue(cr)
                cr.pile_id = None
            rec.queued = [c.car_id for c in queued]
            victims += queued
            origin = {c.car_id: pile_id for c in victims}

            if strategy == "priority":
                self._reassign(victims, rec, origin)
            else:  # time_order：合并同类型所有桩未充车辆，按排队号公平重排
                others = [p for p in self.station.charging_area.get_piles(pile.mode)
                          if p is not pile and p.status is PileStatus.RUNNING]
                origin.update({c.car_id: p.pile_id for p in others
                               for c in p.queue.get_queuing_cars()})
                collected = self.scheduler.collect_uncharged(others)
                merged = self.scheduler.sort_by_queue_number(victims + collected)
                self._reassign(merged, rec, origin)

            self.fault_repo.save(rec)
        finally:
            # (5) 恢复叫号（与暂停成对，构成事务边界）
            self.resume_waiting_area_dispatch()
        return rec

    def _reassign(self, cars: List[ChargingRequest], rec: FaultRecord,
                  origin: dict) -> None:
        """逐车选最优桩安置；安置不下的按原序回等待队列队首。"""
        now = self.clock.now()
        leftovers: List[ChargingRequest] = []
        for cr in cars:
            src = origin.get(cr.car_id, "?")
            target = self.scheduler.assign_pile(cr, self.station.charging_area.get_all_piles(), now)
            if target is not None:
                self._place(cr, target)
                rec.plan.append({"carId": cr.car_id, "from": src, "to": target.pile_id})
            else:
                leftovers.append(cr)
                rec.plan.append({"carId": cr.car_id, "from": src, "to": "等候区队首"})
        for cr in leftovers:
            cr.status = RequestStatus.WAITING
            cr.pile_id = None
            self.request_repo.save(cr)
        self.station.waiting_area.requeue_front_all(leftovers)

    # ---- 故障恢复（系统事件 recoverPile）----
    def handle_recovery(self, pile_id: str) -> dict:
        pile = self.station.find_pile(pile_id)
        if pile.status is not PileStatus.FAULT:
            raise BusinessError(f"{pile_id} 不在故障状态")
        now = self.clock.now()
        pile.status = PileStatus.RUNNING
        pile.powered = True
        pile.accept_new_request = True

        # 回填故障档案的恢复时间
        for item in self.fault_repo.list_all():
            if item["pileId"] == pile_id and not item["recoverTime"]:
                rec = FaultRecord(item["faultId"], item["pileId"], item["faultType"],
                                  item["strategy"], _parse(item["faultTime"]))
                rec.interrupted, rec.queued, rec.plan = (item["interrupted"], item["queued"],
                                                         item["plan"])
                rec.recover_time = now
                self.fault_repo.save(rec)
                break

        plan: List[dict] = []
        same_piles = [p for p in self.station.charging_area.get_piles(pile.mode)
                      if p.status is PileStatus.RUNNING]
        has_queued = any(p.queue.get_queuing_cars() for p in same_piles)
        if has_queued:
            # 同类型还有车排队 → 暂停叫号，收集未充车辆按排队号整体重排（用上新恢复的桩）
            self.pause_waiting_area_dispatch()
            try:
                collected = self.scheduler.collect_uncharged(same_piles)
                merged = self.scheduler.sort_by_queue_number(collected)
                for cr in merged:
                    target = self.scheduler.assign_pile(cr, self.station.charging_area.get_all_piles(), now)
                    if target is not None:
                        self._place(cr, target)
                        plan.append({"carId": cr.car_id, "to": target.pile_id})
                    else:
                        cr.status = RequestStatus.WAITING
                        cr.pile_id = None
                        self.station.waiting_area.requeue_front(cr)
                        self.request_repo.save(cr)
                        plan.append({"carId": cr.car_id, "to": "等候区队首"})
            finally:
                self.resume_waiting_area_dispatch()
        else:
            self.try_auto_dispatch()
        return {"pileId": pile_id, "plan": plan}


def _parse(s):
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S") if s else None
