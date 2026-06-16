"""PileService：充电桩运维与监控用例编排（系统事件 10–15）。

powerOn / setParameters(委托 BillingService) / runPile(Start_ChargingPile) /
powerOff / Query_PileState / Query_QueueState。
"""
from __future__ import annotations

from typing import List

from ..domain.enums import BusinessError, PileStatus, RequestStatus
from ..domain.models import ChargingStation


class PileService:
    def __init__(self, station: ChargingStation, clock, schedule_service,
                 billing_service, request_repo):
        self.station = station
        self.clock = clock
        self.schedule_service = schedule_service
        self.billing_service = billing_service
        self.request_repo = request_repo

    # ---- 事件 10：powerOn 启动（上电）----
    def power_on(self, pile_id: str) -> dict:
        pile = self.station.find_pile(pile_id)
        pile.power_on()  # 幂等上电（故障桩会在 power_on 内抛错要求先恢复）
        return pile.snapshot(self.clock.now())

    # ---- 事件 11：setParameters 设置计费参数（委托计费子系统）----
    def set_parameters(self, dto: dict) -> dict:
        rule = self.billing_service.set_parameters(dto)
        return rule.to_dict()

    # ---- 事件 12：runPile 运行充电桩 ----
    def run_pile(self, pile_id: str) -> dict:
        pile = self.station.find_pile(pile_id)
        pile.run()
        # 多出可用车位，立即触发叫号
        self.schedule_service.try_auto_dispatch()
        return pile.snapshot(self.clock.now())

    # ---- 事件 13：powerOff 关闭充电桩 ----
    def power_off(self, pile_id: str) -> dict:
        pile = self.station.find_pile(pile_id)
        if pile.status is PileStatus.FAULT:
            # 故障桩须先"故障恢复"再操作：直接断电会抹掉 FAULT 状态、令恢复用例无法执行
            raise BusinessError(f"{pile_id} 处于故障状态，请先执行「故障恢复」再关闭")
        if pile.status is PileStatus.OFF and not pile.powered:
            raise BusinessError(f"{pile_id} 已关闭")
        now = self.clock.now()
        result = {"pileId": pile_id, "requeued": [], "delayed": False}
        # Loop：排队车辆按原序退回等待队列队首（公平性：不踩到队尾）
        queued = pile.queue.get_queuing_cars()
        for cr in queued:
            pile.remove_from_queue(cr)
            cr.status = RequestStatus.WAITING
            cr.pile_id = None
            self.request_repo.save(cr)
        self.station.waiting_area.requeue_front_all(queued)
        result["requeued"] = [c.car_id for c in queued]
        # Alt：有车在充 → 延迟关闭（不强行中断物理充电）；无车 → 直接关
        if pile.queue.get_charging_request():
            pile.accept_new_request = False
            result["delayed"] = True
        else:
            pile.shutdown()
        # 回退车辆可能被其他桩接走
        self.schedule_service.try_auto_dispatch()
        result["snapshot"] = pile.snapshot(now)
        return result

    # ---- 事件 14：Query_PileState 查看所有桩状态（定时刷新）----
    def query_pile_state(self) -> List[dict]:
        now = self.clock.now()
        return [p.snapshot(now) for p in self.station.charging_area.get_all_piles()]

    # ---- 事件 15：Query_QueueState 查看某桩队列（纯读不出队）----
    def query_queue_state(self, pile_id: str) -> dict:
        pile = self.station.find_pile(pile_id)
        now = self.clock.now()
        cars = []
        for cr in pile.queue.get_cars():  # get_cars 拷贝，无出队副作用
            wait_h = max((now - cr.submit_time).total_seconds() / 3600.0, 0.0)
            cars.append({
                "carId": cr.car_id,
                "capacity": cr.capacity,
                "requestedAmount": round(cr.requested_amount, 2),
                "queueNumber": cr.queue_number,
                "status": cr.status.value,
                "statusLabel": cr.status.label,
                "waitTime": round(wait_h, 2),   # 排队时长（自提交起）
                "chargedAmount": round(cr.charged_amount(now, pile.power), 2),
            })
        return {"pileId": pile_id, "estimateWaitTime": round(pile.estimate_wait_time(now), 2),
                "cars": cars}
