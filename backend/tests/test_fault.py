"""故障调度测试：优先级 / 时间顺序 / 故障恢复 / 关桩，覆盖组长 3 场景 + 2 Bonus。"""
import pytest

from app.domain.enums import BusinessError, RequestStatus
from tests.conftest import advance, submit


def _shut(ctx, *pile_ids):
    for pid in pile_ids:
        ctx.pile_service.power_off(pid)


def test_fault_priority_requeue_front(ctx):
    """优先级调度：无可用同型桩时，受灾排队车进入故障重调度队列。
    本用例验证概要设计的 interruptPolicy=manual 路径（中断车置"已中断"由用户重新申请），
    故显式钉住 manual（系统默认已改为验收口径的 requeue）。"""
    ctx.config.data["interruptPolicy"] = "manual"
    _shut(ctx, "T2", "T3")
    submit(ctx, "V1", "T", 40)
    ctx.step()                       # V1 → T1 充电
    submit(ctx, "V2", "T", 20)       # T1 排队
    submit(ctx, "V3", "T", 10)       # T1 排队（满）
    submit(ctx, "V4", "T", 10)       # 等候区
    advance(ctx, hours=1)            # V1 已充 10 度（06:00–07:00 谷时）

    rec = ctx.schedule_service.handle_fault("T1", strategy="priority")

    # 中断车：部分计费 + 已中断 + 需重新申请（概要设计 interruptPolicy=manual）
    assert ctx.charging_service.query_car_state("V1")["status"] == "INTERRUPTED"
    bills = ctx.billing_service.request_bill("V1")
    assert len(bills) == 1
    assert bills[0]["billType"] == "interrupted"
    assert bills[0]["chargeAmount"] == 10.0
    assert bills[0]["totalFee"] == 12.0   # 10×0.4 + 10×0.8
    assert rec.interrupted == ["V1"] and rec.queued == ["V2", "V3"]

    # 受灾排队车不挤占普通等候区容量，进入故障重调度队列；V4 仍在普通等候区
    wq = ctx.station.waiting_area.get_queue(
        ctx.station.find_active_request("V4").mode)
    assert [c.car_id for c in ctx.schedule_service.priority_waiting] == ["V2", "V3"]
    assert [c.car_id for c in wq.get_cars()] == ["V4"]

    # 桩恢复服务后优先叫故障重调度队列
    ctx.pile_service.power_on("T2")
    ctx.pile_service.run_pile("T2")
    ctx.step()
    ctx.step()
    assert ctx.charging_service.query_car_state("V2")["status"] == "CHARGING"
    assert ctx.charging_service.query_car_state("V2")["pileId"] == "T2"


def test_fault_priority_reassign_to_best_pile(ctx):
    """优先级调度：有空位时受灾车调到同类型(等待+充电)最短的桩。"""
    ctx.config.data["interruptPolicy"] = "manual"  # 本用例验证 manual 路径
    submit(ctx, "V1", "T", 10)
    ctx.step()
    submit(ctx, "V2", "T", 100)
    ctx.step()
    submit(ctx, "V3", "T", 100)
    ctx.step()
    submit(ctx, "V4", "T", 100)      # → T1 排队（T1 总时长最短）
    submit(ctx, "V5", "T", 1)        # → T2 排队
    assert ctx.charging_service.query_car_state("V4")["pileId"] == "T1"

    rec = ctx.schedule_service.handle_fault("T1", strategy="priority")
    assert rec.interrupted == ["V1"]
    # V4 被调到积压最小的 T3
    assert ctx.charging_service.query_car_state("V4")["pileId"] == "T3"
    assert {"carId": "V4", "from": "T1", "to": "T3"} in rec.plan


def _build_three_pile_queues(ctx):
    """构造：T1[V1*,V4,V7] T2[V2*,V5] T3[V3*,V6]（*=充电中，排队号 1–7）。"""
    submit(ctx, "V1", "T", 10); ctx.step()
    submit(ctx, "V2", "T", 10); ctx.step()
    submit(ctx, "V3", "T", 10); ctx.step()
    submit(ctx, "V4", "T", 100)
    submit(ctx, "V5", "T", 100)
    submit(ctx, "V6", "T", 100)
    submit(ctx, "V7", "T", 100)
    assert [c.car_id for c in ctx.station.find_pile("T1").queue.get_cars()] == ["V1", "V4", "V7"]
    assert [c.car_id for c in ctx.station.find_pile("T2").queue.get_cars()] == ["V2", "V5"]
    assert [c.car_id for c in ctx.station.find_pile("T3").queue.get_cars()] == ["V3", "V6"]


def test_fault_time_order_merges_and_sorts(ctx):
    """时间顺序调度：合并同类型所有桩未充车辆，按排队号公平重排（充电中的不动）。"""
    ctx.config.data["interruptPolicy"] = "manual"  # 本用例验证 manual 路径
    _build_three_pile_queues(ctx)
    rec = ctx.schedule_service.handle_fault("T1", strategy="time_order")
    assert rec.interrupted == ["V1"]
    # 重排后保持排队号次序：V4 先于 V5/V6/V7 获得位置
    t2 = [c.car_id for c in ctx.station.find_pile("T2").queue.get_cars()]
    t3 = [c.car_id for c in ctx.station.find_pile("T3").queue.get_cars()]
    assert t2 == ["V2", "V4", "V6"]
    assert t3 == ["V3", "V5", "V7"]
    # 充电中的 V2/V3 未被打断
    assert ctx.charging_service.query_car_state("V2")["status"] == "CHARGING"


def test_recovery_redistributes(ctx):
    """故障恢复：同类型还有排队车 → 收集未充车辆按排队号重排（用上恢复的桩）。"""
    ctx.config.data["interruptPolicy"] = "manual"  # 本用例验证 manual 路径
    _build_three_pile_queues(ctx)
    ctx.schedule_service.handle_fault("T1", strategy="time_order")
    result = ctx.schedule_service.handle_recovery("T1")
    assert ctx.station.find_pile("T1").status.value == "RUNNING"
    t1 = [c.car_id for c in ctx.station.find_pile("T1").queue.get_cars()]
    t2 = [c.car_id for c in ctx.station.find_pile("T2").queue.get_cars()]
    t3 = [c.car_id for c in ctx.station.find_pile("T3").queue.get_cars()]
    assert t1 == ["V4", "V7"]
    assert t2 == ["V2", "V5"]
    assert t3 == ["V3", "V6"]
    assert len(result["plan"]) == 4
    ctx.step()
    assert ctx.charging_service.query_car_state("V4")["status"] == "CHARGING"
    # 故障记录已回填恢复时间
    rec = ctx.fault_repo.list_all()[0]
    assert rec["recoverTime"] is not None


def test_interrupt_requeue_policy(ctx):
    """可选策略 interruptPolicy=requeue：中断车按剩余电量优先重新调度。"""
    ctx.config.data["interruptPolicy"] = "requeue"
    submit(ctx, "V1", "T", 40)
    ctx.step()
    advance(ctx, hours=1)            # 已充 10 度
    ctx.schedule_service.handle_fault("T1", strategy="priority")
    state = ctx.charging_service.query_car_state("V1")
    # 部分账单 + 剩余 30 度被调度到其他慢充桩
    assert ctx.billing_service.request_bill("V1")[0]["chargeAmount"] == 10.0
    assert state["requestedAmount"] == 30.0
    assert state["pileId"] in ("T2", "T3")
    ctx.step()
    assert ctx.charging_service.query_car_state("V1")["status"] == "CHARGING"


def test_default_interrupt_policy_is_requeue(ctx):
    """系统默认 interruptPolicy=requeue（验收口径）：被故障打断的车自动续充、
    后续仍可正常"结束充电"（对应验收用例 V1 在 T1 故障后于 09:10 结束的事件）。"""
    assert ctx.config.interruptPolicy == "requeue"
    _shut(ctx, "T2", "T3")          # 仅留 T1，制造"先充后断"
    submit(ctx, "V1", "T", 40)
    ctx.step()
    advance(ctx, hours=1)           # V1 已充 10 度
    ctx.pile_service.power_on("T2"); ctx.pile_service.run_pile("T2")  # 备好可续充桩
    ctx.schedule_service.handle_fault("T1", strategy="priority")
    ctx.step()
    s = ctx.charging_service.query_car_state("V1")
    assert s["status"] in ("QUEUING", "CHARGING")   # 续充而非作废
    assert s["requestedAmount"] == 30.0             # 剩余电量
    assert s["pileId"] == "T2"
    # 续充满后可正常结束并出第二张账单
    advance(ctx, hours=3, minutes=1)
    assert ctx.charging_service.query_car_state("V1")["status"] == "FINISHED"


def test_power_off_requeues_and_delays(ctx):
    """关桩：排队车按原序回等待队列队首；充电中车辆延迟关闭（充完自动关）。"""
    _shut(ctx, "T2", "T3")
    submit(ctx, "V1", "T", 10)
    ctx.step()
    submit(ctx, "V2", "T", 20)
    submit(ctx, "V3", "T", 30)
    result = ctx.pile_service.power_off("T1")
    assert result["requeued"] == ["V2", "V3"]
    assert result["delayed"] is True          # V1 还在充电
    assert ctx.charging_service.query_car_state("V1")["status"] == "CHARGING"
    wq = ctx.station.waiting_area.get_queue(
        ctx.station.find_active_request("V2").mode)
    assert [c.car_id for c in wq.get_cars()] == ["V2", "V3"]
    advance(ctx, hours=1, minutes=1)          # V1 充满
    assert ctx.charging_service.query_car_state("V1")["status"] == "FINISHED"
    pile = ctx.station.find_pile("T1")
    assert pile.status.value == "OFF"         # 延迟关闭兑现，不再叫号
    assert ctx.charging_service.query_car_state("V2")["status"] == "WAITING"


def test_power_off_fault_pile_is_refused(ctx):
    """对故障桩执行关闭被拒绝（否则会抹掉 FAULT 状态、令故障恢复用例无法执行）。"""
    submit(ctx, "V1", "F", 30)
    ctx.step()
    ctx.schedule_service.handle_fault("F1", strategy="priority")
    assert ctx.station.find_pile("F1").status.value == "FAULT"
    with pytest.raises(BusinessError):
        ctx.pile_service.power_off("F1")
    # 故障状态保留，恢复用例仍可执行
    assert ctx.station.find_pile("F1").status.value == "FAULT"
    ctx.schedule_service.handle_recovery("F1")
    assert ctx.station.find_pile("F1").status.value == "RUNNING"


def test_power_on_run_are_idempotent(ctx):
    """充电桩出厂即 RUNNING；按系统事件顺序演示 powerOn→runPile 应幂等不报错。"""
    pile = ctx.station.find_pile("F1")
    assert pile.status.value == "RUNNING"
    ctx.pile_service.power_on("F1")   # 不应抛"已在运行中"
    ctx.pile_service.run_pile("F1")   # 不应抛"已在运行中"
    assert pile.status.value == "RUNNING"


def test_bonus_single_optimal_grouping(ctx):
    """Bonus 单次调度：枚举发现“两车同桩”优于“贪心分桩”的方案。"""
    ctx.config.data["dispatchMode"] = "single_optimal"
    _shut(ctx, "T3")
    # T1 积压 10h：V0 充电中(100度)
    ctx.config.data["dispatchMode"] = "default"
    submit(ctx, "V0", "T", 100)
    ctx.step()
    ctx.config.data["dispatchMode"] = "single_optimal"
    # A(1h) B(10h) 同时等待：最优=都进空闲的 T2（Σ=1+11=12 < 分桩 21）
    submit(ctx, "A", "T", 10)
    submit(ctx, "B", "T", 100)
    ctx.step()
    assert ctx.charging_service.query_car_state("A")["pileId"] == "T2"
    assert ctx.charging_service.query_car_state("B")["pileId"] == "T2"
    assert [c.car_id for c in ctx.station.find_pile("T2").queue.get_cars()] == ["A", "B"]


def test_bonus_batch_optimal_triggers_on_equality(ctx):
    """Bonus 批量调度：等候区车数 == 空位总数 时一次性全局最优（同模式约束罚∞）。"""
    _shut(ctx, "T2", "T3")
    # 填满 F1,F2（各 3）与 T1（3）：头车 1h 完成
    for car, mode, amt in [
            ("F-A", "F", 30), ("F-B", "F", 30),     # F1/F2 充电中（1h）
            ("F-C", "F", 90), ("F-D", "F", 90),     # 排队
            ("F-E", "F", 90), ("F-F", "F", 90),
            ("T-A", "T", 10),                        # T1 充电中（1h）
            ("T-B", "T", 100), ("T-C", "T", 100)]:   # T1 排队
        submit(ctx, car, mode, amt)
        ctx.step()
    assert ctx.station.charging_area.get_all_free_spots() == 0
    # 切换批量模式后，3 辆车进入等候区等待批量时机
    ctx.config.data["dispatchMode"] = "batch_optimal"
    submit(ctx, "W-F1", "F", 60)
    submit(ctx, "W-F2", "F", 30)
    submit(ctx, "W-T1", "T", 50)
    for car in ("W-F1", "W-F2", "W-T1"):
        assert ctx.charging_service.query_car_state(car)["status"] == "WAITING"
    # 1 小时后 F1/F2/T1 队首同时充满 → 释放 3 个空位 == 等候区 3 辆 → 批量触发
    advance(ctx, hours=1, minutes=1)
    sf1 = ctx.charging_service.query_car_state("W-F1")
    sf2 = ctx.charging_service.query_car_state("W-F2")
    st1 = ctx.charging_service.query_car_state("W-T1")
    assert {sf1["pileId"], sf2["pileId"]} == {"F1", "F2"}   # 快充车进快充桩
    assert st1["pileId"] == "T1"                            # 慢充车进慢充桩
