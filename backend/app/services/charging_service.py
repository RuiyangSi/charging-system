"""ChargingService：充电申请用例编排（系统事件 1–7）。

E_chargingRequest / Modify_Amount / Modify_Mode / Query_Car_State /
Start_Charging(设备上报) / Query_Charging_State / End_Charging(设备上报) / 取消充电。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from ..domain.enums import BusinessError, ChargeMode, PileStatus, RequestStatus
from ..domain.models import ChargingRequest, ChargingStation


class ChargingService:
    def __init__(self, station: ChargingStation, clock, request_repo, user_repo,
                 billing_service):
        self.station = station
        self.clock = clock
        self.request_repo = request_repo
        self.user_repo = user_repo
        self.billing_service = billing_service
        self.schedule_service = None  # 由 AppContext 注入（双向依赖）

    # ---- 事件 1：E_chargingRequest 提交充电申请 ----
    def submit_request(self, car_id: str, mode_str: str, amount: float) -> dict:
        car_id = str(car_id).strip()
        if not car_id:
            raise BusinessError("车牌号不能为空")
        mode = ChargeMode.parse(mode_str)
        amount = float(amount)
        if amount <= 0:
            raise BusinessError("请求充电量必须大于 0")
        user = self.user_repo.ensure(car_id)
        now = self.clock.now()

        # 创建请求（创建者：Service 持有初始数据）
        cr = ChargingRequest(self.station.next_request_id(), car_id, mode,
                             amount, user["capacity"], now)
        self.station.register_request(cr)  # 校验一车一活动请求
        # 入等待队列
        self.station.waiting_area.enqueue(cr)
        # 分配唯一排队号
        number, seq = self.station.next_queue_number(mode)
        cr.set_queue_number(number, seq)
        self.request_repo.save(cr)
        # 系统自动叫号
        self.schedule_service.dispatch(mode)
        return self.query_car_state(car_id)

    # ---- 事件 2：Modify_Amount 修改充电量 ----
    def modify_amount(self, car_id: str, amount: float) -> dict:
        cr = self._require_active(car_id)
        if cr.status is RequestStatus.CHARGING:
            raise BusinessError("充电中不可修改充电量")
        amount = float(amount)
        if amount <= 0:
            raise BusinessError("请求充电量必须大于 0")
        cr.requested_amount = amount       # 排队位置不变
        cr.modify_time = self.clock.now()
        self.request_repo.save(cr)
        return self.query_car_state(car_id)

    # ---- 事件 3：Modify_Mode 修改充电模式 ----
    def modify_mode(self, car_id: str, mode_str: str) -> dict:
        cr = self._require_active(car_id)
        new_mode = ChargeMode.parse(mode_str)
        if cr.status is RequestStatus.CHARGING:
            raise BusinessError("充电中不可修改充电模式")
        if new_mode is cr.mode:
            raise BusinessError("充电模式未变化")
        old_mode = cr.mode
        if cr.status is RequestStatus.QUEUING:
            # 已占充电区车位：退还资源，回退“等待中”
            pile = self.station.find_pile(cr.pile_id)
            pile.remove_from_queue(cr)
            cr.pile_id = None
            cr.status = RequestStatus.WAITING
            self.station.waiting_area.get_queue(old_mode).add_last(cr)
        # 移到新模式队列末尾并重新发号（视为该模式新到达，保证号序=先来后到）
        self.station.waiting_area.move_to_queue(cr, new_mode)
        cr.mode = new_mode
        number, seq = self.station.next_queue_number(new_mode)
        cr.set_queue_number(number, seq)
        cr.modify_time = self.clock.now()
        self.request_repo.save(cr)
        # 新旧两模式调度局面均变化，各触发一次叫号
        self.schedule_service.dispatch(old_mode)
        self.schedule_service.dispatch(new_mode)
        return self.query_car_state(car_id)

    # ---- 取消充电（含充电中提前结束）----
    def cancel(self, car_id: str) -> dict:
        cr = self._require_active(car_id)
        if cr.status is RequestStatus.CHARGING:
            # 充电中“结束充电”：按已充电量正常结算
            return self.end_charging(cr.pile_id, reason="user")
        mode = cr.mode
        if cr.status is RequestStatus.WAITING:
            self.station.waiting_area.remove(cr)
        elif cr.status is RequestStatus.QUEUING:
            pile = self.station.find_pile(cr.pile_id)
            pile.remove_from_queue(cr)
            cr.pile_id = None
        cr.status = RequestStatus.CANCELED
        cr.end_time = self.clock.now()
        self.station.release_active(cr)
        self.request_repo.save(cr)
        self.schedule_service.dispatch(mode)  # 释放的资源立即叫号
        return {"carId": car_id, "status": cr.status.value, "statusLabel": cr.status.label}

    # ---- 事件 4：Query_Car_State 查看排队状态（纯查询）----
    def query_car_state(self, car_id: str) -> dict:
        cr = self.station.find_latest_request(car_id)
        if cr is None:
            raise BusinessError(f"车辆 {car_id} 没有充电请求")
        now = self.clock.now()
        power = self._power_of(cr)
        data = cr.brief(now, power)
        data["location"] = self.station.location_label(cr)
        data["carsBefore"] = None
        data["estimateWait"] = None
        if cr.status is RequestStatus.WAITING:
            queue = self.station.waiting_area.get_queue(cr.mode)
            data["carsBefore"] = queue.get_cars_before(cr)
            data["estimateWait"] = self.estimate_wait_for_waiting(cr, now)
        elif cr.status is RequestStatus.QUEUING:
            pile = self.station.find_pile(cr.pile_id)
            ahead = []
            for c in pile.queue.get_cars():
                if c is cr:
                    break
                ahead.append(c)
            data["carsBefore"] = len(ahead)
            data["estimateWait"] = round(sum(
                c.remaining_duration_h(now, pile.power) for c in ahead), 2)
        elif cr.status is RequestStatus.CHARGING:
            data["carsBefore"] = 0
            data["estimateWait"] = 0.0
        return data

    # ---- 事件 6：Query_Charging_State 查看充电状态（纯查询+实时算费）----
    def query_charging_state(self, car_id: str) -> dict:
        cr = self.station.find_latest_request(car_id)
        if cr is None:
            raise BusinessError(f"车辆 {car_id} 没有充电请求")
        now = self.clock.now()
        power = self._power_of(cr)
        detail = cr.brief(now, power)
        detail["location"] = self.station.location_label(cr)
        if cr.status is RequestStatus.CHARGING:
            pile = self.station.find_pile(cr.pile_id)
            detail["estimate"] = self.billing_service.estimate(cr, pile, now)
            detail["power"] = pile.power
            remain_h = cr.remaining_duration_h(now, pile.power)
            detail["remainingDuration"] = round(remain_h, 2)
            finish = now + timedelta(hours=remain_h)
            detail["expectedEndTime"] = finish.strftime("%H:%M:%S")
        return detail

    # ---- 事件 5：Start_Charging 开始充电（充电桩设备上报）----
    def start_charging(self, pile_id: str) -> dict:
        pile = self.station.find_pile(pile_id)
        if pile.status is not PileStatus.RUNNING:
            raise BusinessError(f"{pile_id} 未在运行")
        head = pile.queue.peek()
        if head is None or head.status is not RequestStatus.QUEUING:
            raise BusinessError(f"{pile_id} 没有等待开始充电的车辆")
        head.status = RequestStatus.CHARGING
        head.charging_start_time = self.clock.now()  # 分时电价计费起点
        self.request_repo.save(head)
        return head.brief(self.clock.now(), pile.power)

    # ---- 事件 7：End_Charging 结束充电（设备上报充满 / 用户提前结束）----
    def end_charging(self, pile_id: str, reason: str = "full") -> dict:
        pile = self.station.find_pile(pile_id)
        cr = pile.queue.get_charging_request()
        if cr is None:
            raise BusinessError(f"{pile_id} 当前没有充电中的车辆")
        now = self.clock.now()
        charged_now = cr.charged_amount(now, pile.power)
        truly_full = pile.power > 0 and charged_now >= cr.requested_amount - 1e-9
        if reason == "full" and truly_full:
            # 真正充满：按理论完成时刻精确结算，消除引擎轮询间隔误差
            end_time = cr.charging_start_time + timedelta(
                hours=cr.requested_amount / pile.power)
            end_time = min(end_time, now)
            actual = cr.requested_amount
        else:
            # 未充满即结束（用户提前结束 / 设备误报"完成"）：按已充电量如实结算，不虚增到请求量
            end_time = now
            actual = charged_now
        cr.actual_amount = round(actual, 4)
        cr.end_time = end_time
        cr.status = RequestStatus.FINISHED
        # 出队 + 释放车位
        pile.dequeue_head()
        duration = (end_time - cr.charging_start_time).total_seconds() / 3600.0
        pile.record_finished(actual, duration)
        # 结算：创建订单 → 算费 → 创建账单
        bill = self.billing_service.settle(cr, pile, end_time)
        self.station.release_active(cr)
        self.request_repo.save(cr)
        # 设计 UC7 Alt：被预约关闭则关桩不叫号；否则自动叫号
        if pile.status is PileStatus.RUNNING and not pile.accept_new_request:
            pile.shutdown()
        else:
            self.schedule_service.dispatch(pile.mode)
        result = cr.brief(now)
        result["bill"] = bill.to_dict()
        return result

    # ---- 辅助 ----
    def _require_active(self, car_id: str) -> ChargingRequest:
        cr = self.station.find_active_request(car_id)
        if cr is None:
            raise BusinessError(f"车辆 {car_id} 没有进行中的充电请求")
        return cr

    def _power_of(self, cr: ChargingRequest) -> Optional[float]:
        if cr.pile_id:
            pile = self.station.charging_area.find_pile(cr.pile_id)
            if pile:
                return pile.power
        piles = self.station.charging_area.get_piles(cr.mode)
        return piles[0].power if piles else None

    def estimate_wait_for_waiting(self, cr: ChargingRequest, now) -> Optional[float]:
        """等候区车辆的预计等待：把前车依次填入当前积压最小的同模式运行桩后取最小积压。"""
        piles = [p for p in self.station.charging_area.get_piles(cr.mode)
                 if p.status is PileStatus.RUNNING and p.accept_new_request]
        if not piles:
            return None
        loads = [p.estimate_wait_time(now) for p in piles]
        queue = self.station.waiting_area.get_queue(cr.mode)
        for ahead in queue.get_cars():
            if ahead is cr:
                break
            idx = loads.index(min(loads))
            loads[idx] += ahead.requested_amount / piles[idx].power
        return round(min(loads), 2)
