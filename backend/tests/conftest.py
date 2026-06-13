"""测试夹具：独立 AppContext（临时目录 + 内存数据库 + 冻结时钟）。"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.context import AppContext

SIM_DAY = datetime(2026, 6, 11)


@pytest.fixture()
def ctx(tmp_path):
    """冻结在 06:00 的全新系统（默认参数=验收参数：2快30度/h + 3慢10度/h，M=3，N=10）。"""
    c = AppContext(str(tmp_path), db_path=":memory:")
    c.clock.set_speed(0)  # 冻结时钟，测试用 advance() 拨表
    c.clock.set_time(SIM_DAY.replace(hour=6, minute=0, second=0))
    return c


def submit(c: AppContext, car: str, mode: str, amount: float) -> dict:
    return c.charging_service.submit_request(car, mode, amount)


def advance(c: AppContext, hours: float = 0, minutes: float = 0) -> None:
    """拨快模拟时间并执行一次引擎单步（设备上报模拟）。"""
    c.clock.advance(hours * 3600 + minutes * 60)
    c.step()
