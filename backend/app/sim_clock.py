"""虚拟时钟：支持验收要求的比例尺运行（默认 1:10，现实 30s = 系统 5min）。

系统内所有业务时间（提交时间/充电起止/计费时段/账单日期）均取自本时钟。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta


class SimClock:
    def __init__(self, start: datetime, speed: float = 10.0):
        self._lock = threading.Lock()
        self._sim_anchor = start
        self._real_anchor = time.monotonic()
        self._speed = float(speed)

    def now(self) -> datetime:
        with self._lock:
            elapsed = time.monotonic() - self._real_anchor
            # 截断到整秒：消除亚秒级微秒噪声引发的计费时段切分/边界容差/零长度分段问题
            return (self._sim_anchor + timedelta(seconds=elapsed * self._speed)
                    ).replace(microsecond=0)

    @property
    def speed(self) -> float:
        return self._speed

    def set_speed(self, speed: float) -> None:
        """变速：先把当前模拟时刻定格为新锚点，再换倍率，保证时间连续。"""
        if speed < 0:
            raise ValueError("时钟倍率不能为负")
        with self._lock:
            elapsed = time.monotonic() - self._real_anchor
            self._sim_anchor = self._sim_anchor + timedelta(seconds=elapsed * self._speed)
            self._real_anchor = time.monotonic()
            self._speed = float(speed)

    def set_time(self, dt: datetime) -> None:
        with self._lock:
            self._sim_anchor = dt
            self._real_anchor = time.monotonic()

    def advance(self, seconds: float) -> None:
        """测试用：直接拨快模拟时间。"""
        with self._lock:
            self._sim_anchor = self._sim_anchor + timedelta(seconds=seconds)

    def snapshot(self) -> dict:
        now = self.now()
        return {
            "simTime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "hms": now.strftime("%H:%M:%S"),
            "speed": self._speed,
            "paused": self._speed == 0,
        }
