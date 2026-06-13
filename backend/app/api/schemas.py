"""控制层请求体定义（参数校验 + 协议转换）。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class LoginBody(BaseModel):
    carId: str
    capacity: Optional[float] = None


class ChargingRequestBody(BaseModel):
    carId: str
    mode: str        # F=快充 / T=慢充
    amount: float    # 请求充电量（度）


class ModifyAmountBody(BaseModel):
    carId: str
    amount: float


class ModifyModeBody(BaseModel):
    carId: str
    mode: str


class FaultBody(BaseModel):
    faultType: Optional[str] = "设备故障"
    strategy: Optional[str] = None   # priority / time_order，缺省取系统配置


class BillingRuleBody(BaseModel):
    peak: Optional[float] = None
    flat: Optional[float] = None
    valley: Optional[float] = None
    serviceRate: Optional[float] = None
    segments: Optional[List[dict]] = None


class ClockBody(BaseModel):
    speed: Optional[float] = None
    time: Optional[str] = None       # "HH:MM:SS" 或 "YYYY-MM-DD HH:MM:SS"


class ConfigBody(BaseModel):
    FastChargingPileNum: Optional[int] = None
    TrickleChargingPileNum: Optional[int] = None
    ChargingQueueLen: Optional[int] = None
    WaitingAreaSize: Optional[int] = None
    FastPower: Optional[float] = None
    TricklePower: Optional[float] = None
    dispatchMode: Optional[str] = None
    faultStrategy: Optional[str] = None
    interruptPolicy: Optional[str] = None
    clockStart: Optional[str] = None
    clockSpeed: Optional[float] = None


class ResetBody(BaseModel):
    wipeHistory: bool = True
