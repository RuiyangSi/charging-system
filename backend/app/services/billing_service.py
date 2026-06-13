"""BillingService：计费子系统用例编排（创建订单/账单、规则管理、账单查询）。

- settle / partial_settle：结算（创建者：BillingService 建 ChargingOrder/Bill）
- request_bill：按 carId+date 走 BillRepository 检索（有外部检索条件 → 走仓储）
- request_detailed_list：按 billId 取回账单后经 bill.get_order() 内存导航取分时明细
- set_parameters：创建 BillingRule 并落库，对后续计费生效（对应系统事件 setParameters）
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..db import BillingRuleRepository, BillRepository, OrderRepository
from ..domain.billing import Bill, BillingEngine, BillingRule, ChargingOrder
from ..domain.enums import BusinessError
from ..domain.models import ChargingPile, ChargingRequest


class BillingService:
    def __init__(self, engine: BillingEngine, rule_repo: BillingRuleRepository,
                 order_repo: OrderRepository, bill_repo: BillRepository, clock):
        self.engine = engine
        self.rule_repo = rule_repo
        self.order_repo = order_repo
        self.bill_repo = bill_repo
        self.clock = clock
        rule = self.rule_repo.get_current()
        if rule is None:
            rule = BillingRule(effective_time=self._now_str())
            self.rule_repo.save(rule)
        self.rule = rule

    def _now_str(self) -> str:
        return self.clock.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 结算 ----
    def settle(self, cr: ChargingRequest, pile: ChargingPile, end_time: datetime,
               bill_type: str = "normal") -> Bill:
        """创建订单 → BillingEngine 按分时电价算费 → 创建账单并落库。"""
        amount = cr.actual_amount or 0.0
        order_id = f"O{end_time.strftime('%Y%m%d%H%M%S')}-{cr.car_id}"
        order = ChargingOrder(order_id, cr.car_id, pile.pile_id, cr.mode.value,
                              amount, cr.charging_start_time, end_time)
        self.engine.calc_fee(order, self.rule)
        seq = self.bill_repo.count_by_date(end_time.strftime("%Y-%m-%d")) + 1
        bill_id = f"B{end_time.strftime('%Y%m%d')}-{seq:04d}"
        bill = Bill(bill_id, order, bill_type=bill_type)
        self.order_repo.save(order)
        self.bill_repo.save(bill)
        return bill

    def partial_settle(self, cr: ChargingRequest, pile: ChargingPile,
                       now: datetime) -> Optional[Bill]:
        """故障中断：按已充电量部分计费（0 度不出账）。"""
        charged = cr.charged_amount(now, pile.power)
        cr.actual_amount = round(charged, 4)
        cr.end_time = now
        if charged <= 1e-9:
            return None
        return self.settle(cr, pile, now, bill_type="interrupted")

    # ---- 查询 ----
    def request_bill(self, car_id: str, date: Optional[str] = None) -> List[dict]:
        return self.bill_repo.find_by_car_and_date(car_id, date)

    def request_detailed_list(self, bill_id: str) -> dict:
        bill = self.bill_repo.find_by_bill_id(bill_id)
        if not bill:
            raise BusinessError(f"账单不存在: {bill_id}")
        return bill

    # ---- 规则 ----
    def set_parameters(self, dto: dict) -> BillingRule:
        merged = self.rule.to_dict()
        for key in ("peak", "flat", "valley", "serviceRate"):
            if key in dto and dto[key] is not None:
                v = float(dto[key])
                if v < 0:
                    raise BusinessError("电价/服务费不能为负")
                merged[key] = v
        if dto.get("segments"):
            merged["segments"] = self._validate_segments(dto["segments"])
        merged["effectiveTime"] = self._now_str()
        rule = BillingRule.from_dict(merged)
        self.rule_repo.save(rule)
        self.rule = rule
        return rule

    @staticmethod
    def _validate_segments(segments: list) -> list:
        """校验时段表：类型合法、无缺口/重叠、严格覆盖 [0,24)。防止写入坏规则后
        缺口时段静默按谷价计费或 get_price KeyError 直接 500。"""
        norm = []
        for s in segments:
            try:
                lo = float(s["from"]); hi = float(s["to"]); kind = s["kind"]
            except (KeyError, TypeError, ValueError):
                raise BusinessError("时段表格式应为 {from, to, kind}")
            if kind not in ("peak", "flat", "valley"):
                raise BusinessError(f"非法时段类型: {kind}（须为 peak/flat/valley）")
            if not (0 <= lo < hi <= 24):
                raise BusinessError(f"时段区间非法: [{lo}, {hi})，须落在 [0,24) 且 from<to")
            norm.append((lo, hi, kind))
        norm.sort()
        cursor = 0.0
        for lo, hi, _ in norm:
            if abs(lo - cursor) > 1e-9:
                raise BusinessError(f"时段表在 {cursor} 处存在缺口或重叠，须无缝覆盖全天 24 小时")
            cursor = hi
        if abs(cursor - 24) > 1e-9:
            raise BusinessError("时段表须覆盖到 24:00（全天 24 小时）")
        return [{"from": lo, "to": hi, "kind": k} for lo, hi, k in norm]

    def estimate(self, cr: ChargingRequest, pile: ChargingPile, now: datetime) -> dict:
        return self.engine.estimate_current_fee(cr, pile.power, now, self.rule)
