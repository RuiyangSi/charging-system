"""领域层（Domain/Manager）：核心规则与信息专家对象。

对象与方法命名对齐《DESIGN_BIBLE》（Python snake_case 形式）：
ChargingStation(聚合根) / WaitingArea / WaitingQueue / ChargingArea /
ChargingPile(FastPile/SlowPile) / PileQueue / ChargingRequest / FaultRecord。
设计中的 ParkingSpot/occupySpot 在实现中由 PileQueue 的槽位承载（每桩 M 个车位，
队首车位即充电车位）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .enums import BusinessError, ChargeMode, PileStatus, RequestStatus


def fmt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


class ChargingRequest:
    """充电请求（一次充电服务的全生命周期载体）。"""

    def __init__(self, request_id: str, car_id: str, mode: ChargeMode,
                 requested_amount: float, capacity: float, submit_time: datetime):
        self.request_id = request_id
        self.car_id = car_id
        self.mode = mode
        self.requested_amount = float(requested_amount)
        self.capacity = float(capacity)
        self.status = RequestStatus.WAITING
        self.queue_number: Optional[str] = None   # 如 F1 / T3
        self.queue_seq: int = 0                   # 排队号数字部分（时间顺序调度排序键）
        self.pile_id: Optional[str] = None
        self.submit_time = submit_time
        self.modify_time: Optional[datetime] = None
        self.charging_start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.actual_amount: Optional[float] = None
        self.priority_waiting: bool = False

    def set_queue_number(self, number: str, seq: int) -> None:
        self.queue_number, self.queue_seq = number, seq

    def charged_amount(self, now: datetime, power: float) -> float:
        """已充电量（度）：充电中按 时长×功率 实时推算。"""
        if self.status is RequestStatus.CHARGING and self.charging_start_time:
            hours = (now - self.charging_start_time).total_seconds() / 3600.0
            return min(max(hours, 0.0) * power, self.requested_amount)
        if self.status in (RequestStatus.FINISHED, RequestStatus.INTERRUPTED):
            return self.actual_amount or 0.0
        return 0.0

    def remaining_duration_h(self, now: datetime, power: float) -> float:
        """完成本请求还需的充电小时数（充电中扣除已充部分）。"""
        if power <= 0:
            return 0.0
        if self.status is RequestStatus.CHARGING:
            return max(self.requested_amount - self.charged_amount(now, power), 0.0) / power
        return self.requested_amount / power

    def brief(self, now: datetime, power: Optional[float] = None) -> dict:
        charged = self.charged_amount(now, power) if power else (self.actual_amount or 0.0)
        return {
            "requestId": self.request_id,
            "carId": self.car_id,
            "mode": self.mode.value,
            "modeLabel": self.mode.label,
            "requestedAmount": round(self.requested_amount, 2),
            "capacity": self.capacity,
            "status": self.status.value,
            "statusLabel": self.status.label,
            "queueNumber": self.queue_number,
            "pileId": self.pile_id,
            "submitTime": fmt(self.submit_time),
            "modifyTime": fmt(self.modify_time),
            "chargingStartTime": fmt(self.charging_start_time),
            "endTime": fmt(self.end_time),
            "chargedAmount": round(charged, 2),
            "actualAmount": round(self.actual_amount, 2) if self.actual_amount is not None else None,
        }


class PileQueue:
    """充电桩排队队列：容量 M（含队首充电车位）。"""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cars: List[ChargingRequest] = []

    def add_last(self, cr: ChargingRequest) -> None:
        if self.is_full():
            raise BusinessError("充电桩车位已满")
        self.cars.append(cr)

    def remove_first(self) -> Optional[ChargingRequest]:
        return self.cars.pop(0) if self.cars else None

    def remove(self, cr: ChargingRequest) -> None:
        if cr in self.cars:
            self.cars.remove(cr)

    def peek(self) -> Optional[ChargingRequest]:
        return self.cars[0] if self.cars else None

    def get_cars(self) -> List[ChargingRequest]:
        return list(self.cars)

    def get_charging_request(self) -> Optional[ChargingRequest]:
        head = self.peek()
        return head if head and head.status is RequestStatus.CHARGING else None

    def get_queuing_cars(self) -> List[ChargingRequest]:
        return [c for c in self.cars if c.status is RequestStatus.QUEUING]

    def size(self) -> int:
        return len(self.cars)

    def is_full(self) -> bool:
        return len(self.cars) >= self.capacity

    def free_spots(self) -> int:
        return max(self.capacity - len(self.cars), 0)


class ChargingPile:
    """充电桩（父类）。门面方法 add_to_queue/dequeue_head/remove_from_queue 委托内部队列。"""

    def __init__(self, pile_id: str, mode: ChargeMode, power: float, queue_len: int):
        self.pile_id = pile_id
        self.mode = mode
        self.power = float(power)
        self.status = PileStatus.RUNNING
        self.powered = True
        self.accept_new_request = True
        self.queue = PileQueue(queue_len)
        # 累计统计（Query_PileState 返回项）
        self.total_charge_num = 0
        self.total_charge_time = 0.0   # 小时
        self.total_capacity = 0.0      # 度

    # ---- 门面方法 ----
    def add_to_queue(self, cr: ChargingRequest) -> None:
        self.queue.add_last(cr)
        cr.pile_id = self.pile_id

    def dequeue_head(self) -> Optional[ChargingRequest]:
        return self.queue.remove_first()

    def remove_from_queue(self, cr: ChargingRequest) -> None:
        self.queue.remove(cr)

    # ---- 状态 ----
    def is_open_for_dispatch(self) -> bool:
        """是否参与调度选桩：运行中 + 接受新请求（不含车位是否已满的判断，
        供 Scheduler 选出"完成时间最短桩"后再单独判满决定是否等待）。"""
        return self.status is PileStatus.RUNNING and self.accept_new_request

    def is_dispatchable(self) -> bool:
        """可立即被调入车辆：运行中 + 接受新请求 + 有空车位。"""
        return self.is_open_for_dispatch() and not self.queue.is_full()

    def power_on(self) -> None:
        """上电（设计：上电后仍"已关闭"，需运行指令才接客）。幂等：已上电再上电为空操作。"""
        if self.status is PileStatus.FAULT:
            raise BusinessError(f"{self.pile_id} 处于故障状态，须先执行故障恢复")
        self.powered = True

    def run(self) -> None:
        """运行充电桩。幂等：已在运行中再次运行为空操作（仅确保接受新请求），
        便于按系统事件清单正向演示 powerOn→runPile 而不报错。"""
        if self.status is PileStatus.FAULT:
            raise BusinessError(f"{self.pile_id} 处于故障状态，须先执行故障恢复")
        if not self.powered:
            raise BusinessError(f"{self.pile_id} 尚未上电")
        self.status = PileStatus.RUNNING
        self.accept_new_request = True

    def shutdown(self) -> None:
        self.status = PileStatus.OFF
        self.powered = False
        self.accept_new_request = False

    def working_state(self) -> str:
        if self.status is PileStatus.FAULT:
            return "故障"
        if self.status is PileStatus.OFF:
            return "已上电" if self.powered else "已关闭"
        if self.queue.get_charging_request():
            return "充电中"
        return "关闭中" if not self.accept_new_request else "空闲"

    # ---- 信息专家 ----
    def calc_charge_duration(self, amount: float) -> float:
        return amount / self.power if self.power > 0 else 0.0

    def estimate_wait_time(self, now: datetime) -> float:
        """新车若排到本桩，需等待的小时数 = 队列中所有车剩余充电时长之和。"""
        return sum(c.remaining_duration_h(now, self.power) for c in self.queue.get_cars())

    def record_finished(self, amount: float, duration_h: float) -> None:
        self.total_charge_num += 1
        self.total_charge_time += max(duration_h, 0.0)
        self.total_capacity += max(amount, 0.0)

    def snapshot(self, now: datetime) -> dict:
        current = self.queue.get_charging_request()
        return {
            "pileId": self.pile_id,
            "mode": self.mode.value,
            "modeLabel": self.mode.label,
            "power": self.power,
            "status": self.status.value,
            "workingState": self.working_state(),
            "powered": self.powered,
            "acceptNewRequest": self.accept_new_request,
            "queueCapacity": self.queue.capacity,
            "waitingSpots": max(self.queue.capacity - 1, 0),
            "queueLen": self.queue.size(),
            "freeSpots": self.queue.free_spots(),
            "current": current.brief(now, self.power) if current else None,
            "queueCars": [c.brief(now, self.power) for c in self.queue.get_cars()],
            "totalChargeNum": self.total_charge_num,
            "totalChargeTime": round(self.total_charge_time, 2),
            "totalCapacity": round(self.total_capacity, 2),
            "estimateWaitTime": round(self.estimate_wait_time(now), 2),
        }


class FastPile(ChargingPile):
    pass


class SlowPile(ChargingPile):
    pass


class WaitingQueue:
    """等候区单条等待队列（快充/慢充各一条）。"""

    def __init__(self, mode: ChargeMode):
        self.mode = mode
        self.cars: List[ChargingRequest] = []

    def add_last(self, cr: ChargingRequest) -> None:
        self.cars.append(cr)

    def add_first(self, cr: ChargingRequest) -> None:
        self.cars.insert(0, cr)

    def remove_first(self) -> Optional[ChargingRequest]:
        return self.cars.pop(0) if self.cars else None

    def remove(self, cr: ChargingRequest) -> None:
        if cr in self.cars:
            self.cars.remove(cr)

    def peek(self) -> Optional[ChargingRequest]:
        return self.cars[0] if self.cars else None

    def peek_n(self, k: int) -> List[ChargingRequest]:
        return self.cars[:k]

    def get_cars(self) -> List[ChargingRequest]:
        return list(self.cars)

    def get_cars_before(self, cr: ChargingRequest) -> int:
        return self.cars.index(cr) if cr in self.cars else 0

    def size(self) -> int:
        return len(self.cars)


class WaitingArea:
    """等候区：两条模式队列共享容量 N。"""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.queues: Dict[ChargeMode, WaitingQueue] = {
            ChargeMode.FAST: WaitingQueue(ChargeMode.FAST),
            ChargeMode.TRICKLE: WaitingQueue(ChargeMode.TRICKLE),
        }

    def get_queue(self, mode: ChargeMode) -> WaitingQueue:
        return self.queues[mode]

    def get_total_waiting_count(self) -> int:
        return sum(q.size() for q in self.queues.values())

    def is_full(self) -> bool:
        return self.get_total_waiting_count() >= self.capacity

    def enqueue(self, cr: ChargingRequest) -> None:
        if self.is_full():
            raise BusinessError(f"等候区已满，最多容纳 {self.capacity} 辆车等待")
        self.queues[cr.mode].add_last(cr)

    def move_to_queue(self, cr: ChargingRequest, new_mode: ChargeMode) -> None:
        """修改充电模式：出旧模式队列，排到新模式队列末尾。"""
        self.queues[cr.mode].remove(cr)
        self.queues[new_mode].add_last(cr)

    def requeue_front(self, cr: ChargingRequest) -> None:
        """回退到对应模式队列队首（关桩/故障安置不下时，保证公平性）。
        注：回退车辆来自充电区，不受容量 N 限制。"""
        self.queues[cr.mode].add_first(cr)

    def requeue_front_all(self, cars: List[ChargingRequest]) -> None:
        """按原相对顺序整体插到队首：cars[0] 最先被叫号。"""
        for cr in reversed(cars):
            self.requeue_front(cr)

    def remove(self, cr: ChargingRequest) -> None:
        self.queues[cr.mode].remove(cr)

    def get_all_requests(self) -> List[ChargingRequest]:
        """全部等待车辆，按进入等候区先后（提交时间）排序。"""
        cars = [c for q in self.queues.values() for c in q.get_cars()]
        return sorted(cars, key=lambda c: (c.submit_time, c.queue_seq))

    def peek_n(self, mode: ChargeMode, k: int) -> List[ChargingRequest]:
        return self.queues[mode].peek_n(k)


class ChargingArea:
    """充电区：持有全部充电桩。"""

    def __init__(self, piles: List[ChargingPile]):
        self.piles = piles

    def get_all_piles(self) -> List[ChargingPile]:
        return list(self.piles)

    def get_piles(self, mode: ChargeMode) -> List[ChargingPile]:
        return [p for p in self.piles if p.mode is mode]

    def get_free_piles(self, mode: ChargeMode) -> List[ChargingPile]:
        return [p for p in self.get_piles(mode) if p.is_dispatchable()]

    def has_free_spot(self, mode: ChargeMode) -> bool:
        return bool(self.get_free_piles(mode))

    def get_all_free_spots(self) -> int:
        return sum(p.queue.free_spots() for p in self.piles if p.is_dispatchable())

    def find_pile(self, pile_id: str) -> Optional[ChargingPile]:
        for p in self.piles:
            if p.pile_id == pile_id:
                return p
        return None


class FaultRecord:
    """故障记录：登记中断车辆、受影响排队车辆与重排方案。"""

    def __init__(self, fault_id: str, pile_id: str, fault_type: str,
                 strategy: str, fault_time: datetime):
        self.fault_id = fault_id
        self.pile_id = pile_id
        self.fault_type = fault_type
        self.strategy = strategy            # priority / time_order
        self.fault_time = fault_time
        self.recover_time: Optional[datetime] = None
        self.interrupted: List[str] = []    # 充电被中断的车辆（部分计费）
        self.queued: List[str] = []         # 受影响的排队车辆
        self.plan: List[dict] = []          # 重排方案 [{carId, from, to}]

    def to_dict(self) -> dict:
        return {
            "faultId": self.fault_id,
            "pileId": self.pile_id,
            "faultType": self.fault_type,
            "strategy": self.strategy,
            "strategyLabel": "优先级调度" if self.strategy == "priority" else "时间顺序调度",
            "faultTime": fmt(self.fault_time),
            "recoverTime": fmt(self.recover_time),
            "interrupted": self.interrupted,
            "queued": self.queued,
            "plan": self.plan,
        }


class ChargingStation:
    """聚合根（运行时单例）：维护等候区、充电区与全部运行时请求。"""

    def __init__(self, config) -> None:
        piles: List[ChargingPile] = []
        for i in range(int(config.FastChargingPileNum)):
            piles.append(FastPile(f"F{i + 1}", ChargeMode.FAST,
                                  config.FastPower, int(config.ChargingQueueLen)))
        for i in range(int(config.TrickleChargingPileNum)):
            piles.append(SlowPile(f"T{i + 1}", ChargeMode.TRICKLE,
                                  config.TricklePower, int(config.ChargingQueueLen)))
        self.charging_area = ChargingArea(piles)
        self.waiting_area = WaitingArea(int(config.WaitingAreaSize))
        self.requests: Dict[str, ChargingRequest] = {}        # requestId -> cr（全量）
        self.active_by_car: Dict[str, ChargingRequest] = {}   # carId -> 活动请求
        self._queue_counters: Dict[ChargeMode, int] = {ChargeMode.FAST: 0, ChargeMode.TRICKLE: 0}
        self._request_seq = 0

    # ---- 排队号 ----
    def next_queue_number(self, mode: ChargeMode):
        self._queue_counters[mode] += 1
        seq = self._queue_counters[mode]
        return f"{mode.value}{seq}", seq

    def next_request_id(self) -> str:
        self._request_seq += 1
        return f"R{self._request_seq:05d}"

    # ---- 导航 ----
    def find_pile(self, pile_id: str) -> ChargingPile:
        pile = self.charging_area.find_pile(pile_id)
        if not pile:
            raise BusinessError(f"充电桩不存在: {pile_id}")
        return pile

    def find_active_request(self, car_id: str) -> Optional[ChargingRequest]:
        return self.active_by_car.get(car_id)

    def find_latest_request(self, car_id: str) -> Optional[ChargingRequest]:
        active = self.find_active_request(car_id)
        if active:
            return active
        history = [r for r in self.requests.values() if r.car_id == car_id]
        return max(history, key=lambda r: r.submit_time) if history else None

    def register_request(self, cr: ChargingRequest) -> None:
        if (old := self.active_by_car.get(cr.car_id)) and old.status.active:
            raise BusinessError(f"车辆 {cr.car_id} 已有进行中的充电请求（{old.status.label}）")
        self.requests[cr.request_id] = cr
        self.active_by_car[cr.car_id] = cr

    def release_active(self, cr: ChargingRequest) -> None:
        """请求进入终态后，解除“一车一活动请求”占用。"""
        if self.active_by_car.get(cr.car_id) is cr:
            del self.active_by_car[cr.car_id]

    def get_queue_of(self, cr: ChargingRequest):
        """返回请求当前所在队列（等候区队列或充电桩队列）。"""
        if getattr(cr, "priority_waiting", False):
            return None
        if cr.status is RequestStatus.WAITING:
            return self.waiting_area.get_queue(cr.mode)
        if cr.pile_id:
            return self.find_pile(cr.pile_id).queue
        return None

    def location_label(self, cr: ChargingRequest) -> str:
        if getattr(cr, "priority_waiting", False):
            return f"故障重调度队列·{cr.mode.label}"
        if cr.status is RequestStatus.WAITING:
            return f"等候区·{cr.mode.label}"
        if cr.status is RequestStatus.QUEUING:
            return f"{cr.pile_id} 排队队列"
        if cr.status is RequestStatus.CHARGING:
            return f"{cr.pile_id} 充电中"
        return "—"
