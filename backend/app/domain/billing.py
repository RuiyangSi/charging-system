"""计费子系统领域对象：BillingRule / ChargingOrder / Bill / BillingEngine（纯虚构领域服务）。

计费规则（默认值与验收用例一致）：
- 峰时 10:00–15:00, 18:00–21:00 → 1.0 元/度
- 平时 07:00–10:00, 15:00–18:00, 21:00–23:00 → 0.7 元/度
- 谷时 23:00–次日 07:00 → 0.4 元/度
- 服务费 0.8 元/度
充电费 = Σ(时段充入度数 × 时段电价)；总费用 = 充电费 + 服务费。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

SEG_LABELS = {"peak": "峰时", "flat": "平时", "valley": "谷时"}


class BillingRule:
    """分时计费规则（管理员 setParameters 可更新，对后续计费生效）。"""

    # (起始小时, 结束小时, 时段类型)，覆盖全天 24h
    DEFAULT_SEGMENTS: List[Tuple[float, float, str]] = [
        (0, 7, "valley"), (7, 10, "flat"), (10, 15, "peak"),
        (15, 18, "flat"), (18, 21, "peak"), (21, 23, "flat"), (23, 24, "valley"),
    ]

    def __init__(self, peak: float = 1.0, flat: float = 0.7, valley: float = 0.4,
                 service_rate: float = 0.8,
                 segments: Optional[List[Tuple[float, float, str]]] = None,
                 effective_time: Optional[str] = None):
        self.prices = {"peak": float(peak), "flat": float(flat), "valley": float(valley)}
        self.service_rate = float(service_rate)
        self.segments = [tuple(s) for s in (segments or self.DEFAULT_SEGMENTS)]
        self.effective_time = effective_time

    def get_price(self, kind: str) -> float:
        return self.prices[kind]

    def get_service_rate(self) -> float:
        return self.service_rate

    def kind_at(self, dt: datetime) -> str:
        h = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        for start, end, kind in self.segments:
            if start <= h < end:
                return kind
        return "valley"

    def next_boundary_after(self, dt: datetime) -> datetime:
        """dt 之后最近的一个时段边界时刻。"""
        h = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + dt.microsecond / 3.6e9
        bounds = sorted({s for s, _, _ in self.segments} | {e for _, e, _ in self.segments})
        day0 = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        for b in bounds:
            if b > h + 1e-9:
                return day0 + timedelta(hours=b)
        return day0 + timedelta(days=1)  # 跨天：次日 00:00

    def to_dict(self) -> dict:
        return {
            "peak": self.prices["peak"],
            "flat": self.prices["flat"],
            "valley": self.prices["valley"],
            "serviceRate": self.service_rate,
            "segments": [{"from": s, "to": e, "kind": k, "label": SEG_LABELS[k],
                          "price": self.prices[k]} for s, e, k in self.segments],
            "effectiveTime": self.effective_time,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BillingRule":
        segs = None
        if d.get("segments"):
            segs = [(s["from"], s["to"], s["kind"]) if isinstance(s, dict) else tuple(s)
                    for s in d["segments"]]
        return cls(peak=d.get("peak", 1.0), flat=d.get("flat", 0.7),
                   valley=d.get("valley", 0.4),
                   service_rate=d.get("serviceRate", d.get("service_rate", 0.8)),
                   segments=segs, effective_time=d.get("effectiveTime"))


class ChargingOrder:
    """充电订单：充电度数/时长/起止时间/充电费/服务费 + 分时明细。"""

    def __init__(self, order_id: str, car_id: str, pile_id: str, mode: str,
                 amount: float, start_time: datetime, end_time: datetime):
        self.order_id = order_id
        self.car_id = car_id
        self.pile_id = pile_id
        self.mode = mode
        self.amount = float(amount)
        self.start_time = start_time
        self.end_time = end_time
        self.duration_h = max((end_time - start_time).total_seconds() / 3600.0, 0.0)
        self.charge_fee = 0.0
        self.service_fee = 0.0
        self.total_fee = 0.0
        self.segments: List[dict] = []

    def get_segmented_detail(self) -> List[dict]:
        return self.segments


class Bill:
    """账单：持有订单引用（查询详单经 bill.get_order() 内存导航）。"""

    def __init__(self, bill_id: str, order: ChargingOrder, bill_type: str = "normal"):
        self.bill_id = bill_id
        self.order = order
        self.bill_type = bill_type  # normal / interrupted（故障部分计费）
        self.date = order.end_time.strftime("%Y-%m-%d")

    def get_order(self) -> ChargingOrder:
        return self.order

    def to_dict(self) -> dict:
        o = self.order
        return {
            "billId": self.bill_id,
            "carId": o.car_id,
            "date": self.date,
            "pileId": o.pile_id,
            "mode": o.mode,
            "billType": self.bill_type,
            "chargeAmount": round(o.amount, 2),
            "chargeDuration": round(o.duration_h, 2),
            "startTime": o.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": o.end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "totalChargeFee": round(o.charge_fee, 2),
            "totalServiceFee": round(o.service_fee, 2),
            "totalFee": round(o.total_fee, 2),
        }


class BillingEngine:
    """计费引擎（纯虚构领域服务）：分时电价计算，与业务编排解耦。"""

    def compute_charge_fee(self, start: datetime, end: datetime, amount: float,
                           rule: BillingRule, round_segments: bool = True
                           ) -> Tuple[float, List[dict]]:
        """按时段切分 [start, end)，假定恒功率充入 amount 度，返回(充电费, 分时明细)。
        round_segments=True（详单/账单）：每段先取整，保证 Σ(分段)==充电费小计；
        round_segments=False（实时费用）：只对总额取整，与连续积分一致（避免双重取整丢分，
        如 V5 在 08:20 的当前费用应为 27.00 而非 26.99）。"""
        total_h = (end - start).total_seconds() / 3600.0
        if total_h <= 0 or amount <= 0:
            return 0.0, []
        power = amount / total_h
        fee_total = 0.0
        segments: List[dict] = []
        t = start
        while t < end:
            kind = rule.kind_at(t)
            seg_end = min(rule.next_boundary_after(t), end)
            hours = (seg_end - t).total_seconds() / 3600.0
            kwh = power * hours
            price = rule.get_price(kind)
            raw = kwh * price
            fee = round(raw, 2) if round_segments else raw
            fee_total += fee
            segments.append({
                "kind": kind, "label": SEG_LABELS[kind],
                "from": t.strftime("%H:%M"), "to": seg_end.strftime("%H:%M"),
                "kwh": round(kwh, 2), "price": price, "fee": round(fee, 2),
            })
            t = seg_end
        return round(fee_total, 2), segments

    def compute_service_fee(self, amount: float, rule: BillingRule) -> float:
        return max(amount, 0.0) * rule.get_service_rate()

    def calc_fee(self, order: ChargingOrder, rule: BillingRule) -> ChargingOrder:
        charge_fee, segments = self.compute_charge_fee(
            order.start_time, order.end_time, order.amount, rule)
        order.charge_fee = round(charge_fee, 2)
        order.service_fee = round(self.compute_service_fee(order.amount, rule), 2)
        # 合计 = 已取整的充电费 + 已取整的服务费，保证三者账面自洽（避免 X.XX 分项相加差 0.01）
        order.total_fee = round(order.charge_fee + order.service_fee, 2)
        order.segments = segments
        return order

    def estimate_current_fee(self, cr, power: float, now: datetime,
                             rule: BillingRule) -> dict:
        """实时预估（Query_Charging_State）：已充时长 / 已充电量 / 当前费用。"""
        if not cr.charging_start_time:
            return {"chargedAmount": 0.0, "duration": 0.0,
                    "chargeFee": 0.0, "serviceFee": 0.0, "totalFee": 0.0}
        charged = cr.charged_amount(now, power)
        end = now
        if charged >= cr.requested_amount and power > 0:  # 已充满：截到理论完成时刻
            end = cr.charging_start_time + timedelta(hours=cr.requested_amount / power)
        duration = max((end - cr.charging_start_time).total_seconds() / 3600.0, 0.0)
        charge_fee, _ = self.compute_charge_fee(cr.charging_start_time, end, charged, rule,
                                                round_segments=False)
        service_fee = round(self.compute_service_fee(charged, rule), 2)
        charge_fee = round(charge_fee, 2)
        return {
            "chargedAmount": round(charged, 2),
            "duration": round(duration, 2),
            "chargeFee": charge_fee,
            "serviceFee": service_fee,
            "totalFee": round(charge_fee + service_fee, 2),
        }
