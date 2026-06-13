"""计费引擎测试：分时电价切分、验收用例数值核对。"""
from datetime import datetime

from app.domain.billing import BillingEngine, BillingRule

DAY = datetime(2026, 6, 11)
engine = BillingEngine()
rule = BillingRule()  # 峰1.0 / 平0.7 / 谷0.4，服务费0.8


def t(h, m=0, s=0):
    return DAY.replace(hour=h, minute=m, second=s)


def test_acceptance_v1_full_charge():
    """验收 V1：06:00 慢充(10度/h) 40 度 → 4h：谷 1h×10度 + 平 3h×30度。"""
    fee, segs = engine.compute_charge_fee(t(6), t(10), 40.0, rule)
    assert abs(fee - (10 * 0.4 + 30 * 0.7)) < 1e-6  # 4 + 21 = 25
    assert [s["kind"] for s in segs] == ["valley", "flat"]
    assert abs(engine.compute_service_fee(40, rule) - 32.0) < 1e-6
    # 总费用 57.00


def test_acceptance_v1_after_5min():
    """验收表首行：06:05 时 V1 已充 0.83 度、当前费用 1.00。"""
    fee, _ = engine.compute_charge_fee(t(6), t(6, 5), 10 * 5 / 60, rule)
    service = engine.compute_service_fee(10 * 5 / 60, rule)
    charged = 10 * 5 / 60
    assert round(charged, 2) == 0.83
    assert round(fee + service, 2) == 1.00


def test_peak_segments():
    """10:00–15:00 峰时整段。"""
    fee, segs = engine.compute_charge_fee(t(10), t(15), 50.0, rule)
    assert abs(fee - 50.0) < 1e-6
    assert len(segs) == 1 and segs[0]["kind"] == "peak"


def test_cross_midnight():
    """22:00 → 次日 01:00：平 1h + 谷 2h。"""
    end = datetime(2026, 6, 12, 1, 0, 0)
    fee, segs = engine.compute_charge_fee(t(22), end, 9.0, rule)  # 3度/h
    assert abs(fee - (3 * 0.7 + 6 * 0.4)) < 1e-6  # 2.1 + 2.4
    assert [s["kind"] for s in segs] == ["flat", "valley", "valley"]


def test_boundary_alignment():
    """恰好压在时段边界 7:00 上开始。"""
    fee, segs = engine.compute_charge_fee(t(7), t(10), 30.0, rule)
    assert abs(fee - 21.0) < 1e-6
    assert len(segs) == 1 and segs[0]["kind"] == "flat"


def test_fee_rounding_self_consistent():
    """账面自洽：Σ(分段费用) == 充电费小计；分项各自取整后相加 == 合计（无 0.01 错位）。
    取一个会产生多位小数的分段场景（21:46:40 起充 38 度至次日 01:34:40）。"""
    from app.domain.billing import ChargingOrder
    start = DAY.replace(hour=21, minute=46, second=40)
    end = datetime(2026, 6, 12, 1, 34, 40)
    fee, segs = engine.compute_charge_fee(start, end, 38.0, rule)
    assert abs(round(sum(s["fee"] for s in segs), 2) - fee) < 1e-9   # Σ分段 == 小计
    order = ChargingOrder("O1", "Z1", "F1", "F", 38.0, start, end)
    engine.calc_fee(order, rule)
    assert round(order.charge_fee + order.service_fee, 2) == order.total_fee


def test_custom_rule_prices():
    r2 = BillingRule(peak=2.0, flat=1.0, valley=0.5, service_rate=1.0)
    fee, _ = engine.compute_charge_fee(t(9), t(11), 20.0, r2)  # 平1h+峰1h，各10度
    assert abs(fee - (10 * 1.0 + 10 * 2.0)) < 1e-6
    assert abs(engine.compute_service_fee(20, r2) - 20.0) < 1e-6
