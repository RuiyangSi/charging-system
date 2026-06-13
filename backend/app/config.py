"""系统可配置参数（验收时数值可变更）。

参数名与《作业验收用例.xlsx · 测试说明》保持一致：
- FastChargingPileNum     快充桩数量（默认 2）
- TrickleChargingPileNum  慢充桩数量（默认 3）
- ChargingQueueLen        充电桩排队队列长度 M（含正在充电的 1 个车位，默认 3）
- WaitingAreaSize         等候区最大容量 N（默认 10）
功率默认值同验收用例：快充 30 度/h、慢充 10 度/h。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Tuple


def parse_hms(value: str) -> Tuple[int, int, int]:
    """解析 "HH:MM" 或 "HH:MM:SS"（缺省秒为 0）；非法格式抛 ValueError。
    供起始时刻设置容错——管理员填 "06:00" 两段也能正确解析，不再令系统启动崩溃。"""
    parts = str(value).strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"时刻格式应为 HH:MM 或 HH:MM:SS: {value!r}")
    try:
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        raise ValueError(f"时刻含非数字: {value!r}")
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError(f"时刻越界: {value!r}")
    return h, m, s

DEFAULT_CONFIG: Dict[str, Any] = {
    "FastChargingPileNum": 2,
    "TrickleChargingPileNum": 3,
    "ChargingQueueLen": 3,
    "WaitingAreaSize": 10,
    "FastPower": 30.0,          # 度/小时
    "TricklePower": 10.0,       # 度/小时
    # 调度策略：default=按序叫号(等待+充电时长最短选桩)
    #           single_optimal=Bonus 单次调度总时长最短
    #           batch_optimal=Bonus 批量调度总时长最短（等候区车数==空位总数时触发）
    "dispatchMode": "default",
    # 故障再调度缺省策略：priority=优先级调度 / time_order=时间顺序调度
    "faultStrategy": "priority",
    # 故障时正在充电车辆的处理：requeue=按剩余电量最高优先重新调度续充（验收口径，默认）
    #                         manual=部分计费+置已中断+需用户重新申请（概要设计可选）
    # 验收用例中被故障打断的车（如 V1）随后仍有"结束充电"事件，须续充而非作废，故默认 requeue。
    "interruptPolicy": "requeue",
    # 虚拟时钟：验收比例尺 1:10（现实 30s = 系统 5min），起始 06:00
    "clockStart": "06:00:00",
    "clockSpeed": 10.0,
}


class SystemConfig:
    """可持久化的系统参数，加载/保存到 config.json。"""

    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for k in DEFAULT_CONFIG:
                    if k in saved:
                        self.data[k] = saved[k]
            except (json.JSONDecodeError, OSError):
                pass  # 配置损坏时回退默认值

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def update(self, patch: Dict[str, Any]) -> None:
        """全或无更新：先校验全部条目，全部通过后再统一写入并落盘，
        避免某项校验失败时前面的项已半生效造成内存/磁盘配置不一致。"""
        staged: Dict[str, Any] = {}
        for k, v in patch.items():
            if k not in DEFAULT_CONFIG:
                raise ValueError(f"未知配置项: {k}")
            expect = type(DEFAULT_CONFIG[k])
            if expect in (int, float):
                v = expect(v)
                if k != "clockSpeed" and v <= 0:
                    raise ValueError(f"{k} 必须为正数")
                if k == "clockSpeed" and v < 0:
                    raise ValueError("clockSpeed 不能为负")
            elif k == "clockStart":
                h, m, s = parse_hms(v)        # 非法格式立即抛错，不写入坏值
                v = f"{h:02d}:{m:02d}:{s:02d}"
            staged[k] = v
        self.data.update(staged)
        self.save()

    def __getattr__(self, item: str) -> Any:
        try:
            return self.__dict__["data"][item]
        except KeyError:
            raise AttributeError(item)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.data)
