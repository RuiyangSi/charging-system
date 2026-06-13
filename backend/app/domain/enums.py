"""领域枚举与业务异常。"""
from __future__ import annotations

from enum import Enum


class ChargeMode(str, Enum):
    FAST = "F"      # 快充
    TRICKLE = "T"   # 慢充

    @property
    def label(self) -> str:
        return "快充" if self is ChargeMode.FAST else "慢充"

    @staticmethod
    def parse(value: str) -> "ChargeMode":
        v = str(value).strip().upper()
        if v in ("F", "FAST", "快充", "快"):
            return ChargeMode.FAST
        if v in ("T", "TRICKLE", "SLOW", "慢充", "慢"):
            return ChargeMode.TRICKLE
        raise BusinessError(f"无效充电模式: {value}")


class RequestStatus(str, Enum):
    WAITING = "WAITING"          # 等待中（等候区）
    QUEUING = "QUEUING"          # 排队中（充电桩队列，未充电）
    CHARGING = "CHARGING"        # 充电中
    FINISHED = "FINISHED"        # 已完成
    INTERRUPTED = "INTERRUPTED"  # 已中断（桩故障）
    CANCELED = "CANCELED"        # 已取消

    @property
    def label(self) -> str:
        return {
            RequestStatus.WAITING: "等待中",
            RequestStatus.QUEUING: "排队中",
            RequestStatus.CHARGING: "充电中",
            RequestStatus.FINISHED: "已完成",
            RequestStatus.INTERRUPTED: "已中断",
            RequestStatus.CANCELED: "已取消",
        }[self]

    @property
    def active(self) -> bool:
        """是否仍占用系统资源（终态返回 False）。"""
        return self in (RequestStatus.WAITING, RequestStatus.QUEUING, RequestStatus.CHARGING)


class PileStatus(str, Enum):
    OFF = "OFF"          # 已关闭
    RUNNING = "RUNNING"  # 运行中
    FAULT = "FAULT"      # 故障

    @property
    def label(self) -> str:
        return {
            PileStatus.OFF: "已关闭",
            PileStatus.RUNNING: "运行中",
            PileStatus.FAULT: "故障",
        }[self]


class BusinessError(Exception):
    """业务校验失败，最终以 HTTP 400 返回给客户端。"""
