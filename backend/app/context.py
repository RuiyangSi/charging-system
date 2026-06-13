"""AppContext：装配四层对象（运行时单例），并提供模拟引擎单步 step()。

step() 扮演“充电桩设备”角色：
- 队首车辆就位 → 设备上报 Start_Charging
- 已充电量达到请求电量 → 设备上报 End_Charging
- 资源变动后的系统自动叫号兜底
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Optional

from .config import SystemConfig, parse_hms
from .db import (BillingRuleRepository, BillRepository, ChargingRequestRepository,
                 Database, FaultRepository, OrderRepository, UserRepository)
from .domain.billing import BillingEngine
from .domain.enums import PileStatus, RequestStatus
from .domain.models import ChargingStation
from .domain.scheduler import Scheduler
from .services.billing_service import BillingService
from .services.charging_service import ChargingService
from .services.pile_service import PileService
from .services.schedule_service import ScheduleService
from .sim_clock import SimClock


class AppContext:
    def __init__(self, data_dir: str, db_path: Optional[str] = None):
        os.makedirs(data_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.config = SystemConfig(os.path.join(data_dir, "config.json"))
        self.clock = SimClock(self._start_datetime(), float(self.config.clockSpeed))
        self.db = Database(db_path or os.path.join(data_dir, "charging.db"))

        self.user_repo = UserRepository(self.db)
        self.request_repo = ChargingRequestRepository(self.db)
        self.order_repo = OrderRepository(self.db)
        self.bill_repo = BillRepository(self.db, self.order_repo)
        self.fault_repo = FaultRepository(self.db)
        self.rule_repo = BillingRuleRepository(self.db)

        # 启动清理：上次进程残留的非终态请求（内存已丢失，成为"僵尸充电中"）置为已取消，
        # 避免重启后用户端历史长期显示"充电中"且永不出账。
        self.request_repo.cancel_orphans()

        self._build_runtime()

    def _start_datetime(self) -> datetime:
        h, m, s = parse_hms(self.config.clockStart)   # 容错解析 HH:MM / HH:MM:SS
        return datetime.now().replace(hour=h, minute=m, second=s, microsecond=0)

    def _build_runtime(self) -> None:
        """构建聚合根与服务（系统启动 / 重置时调用）。"""
        self.station = ChargingStation(self.config)
        self.scheduler = Scheduler()
        self.billing_engine = BillingEngine()
        self.billing_service = BillingService(self.billing_engine, self.rule_repo,
                                              self.order_repo, self.bill_repo, self.clock)
        self.schedule_service = ScheduleService(self.station, self.scheduler, self.clock,
                                                self.config, self.billing_service,
                                                self.request_repo, self.fault_repo)
        self.charging_service = ChargingService(self.station, self.clock, self.request_repo,
                                                self.user_repo, self.billing_service)
        self.charging_service.schedule_service = self.schedule_service
        self.pile_service = PileService(self.station, self.clock, self.schedule_service,
                                        self.billing_service, self.request_repo)

    def reset(self, wipe_history: bool = True) -> None:
        """系统重置（验收开跑前使用）：重建运行时状态 + 时钟归位到起始时刻。"""
        with self.lock:
            if wipe_history:
                self.db.clear_runtime_tables()
            self._build_runtime()
            self.clock.set_time(self._start_datetime())
            self.clock.set_speed(float(self.config.clockSpeed))

    # ---- 模拟引擎单步（也供测试直接调用）----
    def step(self) -> None:
        with self.lock:
            now = self.clock.now()
            piles = self.station.charging_area.get_all_piles()
            # ① 充满自动结束（设备上报 End_Charging）
            for pile in piles:
                cr = pile.queue.get_charging_request()
                if cr and cr.charged_amount(now, pile.power) >= cr.requested_amount - 1e-9:
                    self.charging_service.end_charging(pile.pile_id, reason="full")
            # ② 系统自动叫号兜底
            self.schedule_service.try_auto_dispatch()
            # ③ 队首车辆开始充电（设备上报 Start_Charging）
            for pile in piles:
                if pile.status is PileStatus.RUNNING:
                    head = pile.queue.peek()
                    if head is not None and head.status is RequestStatus.QUEUING:
                        self.charging_service.start_charging(pile.pile_id)


_context: Optional[AppContext] = None


def init_context(data_dir: str, db_path: Optional[str] = None) -> AppContext:
    global _context
    _context = AppContext(data_dir, db_path)
    return _context


def get_context() -> AppContext:
    assert _context is not None, "AppContext 尚未初始化"
    return _context
