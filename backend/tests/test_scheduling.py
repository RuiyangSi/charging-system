"""调度与生命周期测试：叫号、容量、修改/取消、充满结算（对照验收用例前几步）。"""
import pytest

from app.domain.enums import BusinessError, RequestStatus
from tests.conftest import advance, submit


def test_submit_dispatch_and_start(ctx):
    """V1 提交后立即被调度进慢充桩并开始充电（验收 06:00 首行）。"""
    submit(ctx, "V1", "T", 40)
    ctx.step()
    state = ctx.charging_service.query_car_state("V1")
    assert state["status"] == "CHARGING"
    assert state["pileId"] == "T1"
    assert state["queueNumber"] == "T1"


def test_acceptance_first_rows(ctx):
    """验收前两行：06:00 V1(T,40)→T1；06:05 V2(T,30)→T2；V1 已充0.83度/费1.00。"""
    submit(ctx, "V1", "T", 40)
    ctx.step()
    advance(ctx, minutes=5)
    submit(ctx, "V2", "T", 30)
    ctx.step()
    s1 = ctx.charging_service.query_charging_state("V1")
    s2 = ctx.charging_service.query_charging_state("V2")
    assert s1["pileId"] == "T1" and s2["pileId"] == "T2"
    assert s1["estimate"]["chargedAmount"] == 0.83
    assert s1["estimate"]["totalFee"] == 1.00
    assert s2["estimate"]["chargedAmount"] == 0.0


def test_fast_area_fills_then_waiting(ctx):
    """2 快充桩 × M=3 = 6 位；第 7 辆快充车留在等候区（验收 V13 场景）。"""
    for i in range(1, 8):
        submit(ctx, f"F-CAR{i}", "F", 30)
        ctx.step()
    states = [ctx.charging_service.query_car_state(f"F-CAR{i}") for i in range(1, 8)]
    in_area = [s for s in states if s["pileId"]]
    waiting = [s for s in states if s["status"] == "WAITING"]
    assert len(in_area) == 6 and len(waiting) == 1
    assert waiting[0]["carId"] == "F-CAR7"
    assert waiting[0]["location"] == "等候区·快充"


def test_waiting_area_is_non_blocking(ctx):
    """等候区容量 N 为标称值、不硬性拒绝（验收用例峰值排队会超过 N，
    原始需求亦为"可容纳任意数量车辆"）：充电区占满后继续提交不抛错，全部进等候区排队。"""
    # 5 桩 × 3 位 = 15 进充电区
    for i in range(1, 16):
        submit(ctx, f"C{i}", "T" if i % 2 else "F", 10)
        ctx.step()
    # 再提交 12 辆（超过 N=10），均不被拒绝
    rejected = 0
    for i in range(16, 28):
        try:
            submit(ctx, f"C{i}", "T", 10)
        except BusinessError:
            rejected += 1
    assert rejected == 0
    waiting = ctx.station.waiting_area.get_total_waiting_count()
    assert waiting == 12  # 全部进入等候区，容量 N=10 仅作展示提示


def test_queue_number_sequence(ctx):
    submit(ctx, "A1", "F", 10)
    submit(ctx, "A2", "F", 10)
    submit(ctx, "A3", "T", 10)
    assert ctx.charging_service.query_car_state("A1")["queueNumber"] == "F1"
    assert ctx.charging_service.query_car_state("A2")["queueNumber"] == "F2"
    assert ctx.charging_service.query_car_state("A3")["queueNumber"] == "T1"


def test_assign_pile_balances_load(ctx):
    """选桩 = (等待+充电)时长最短：T1 已有 40 度任务，下一辆应去 T2。"""
    submit(ctx, "V1", "T", 40)
    ctx.step()
    submit(ctx, "V2", "T", 30)
    ctx.step()
    assert ctx.charging_service.query_car_state("V2")["pileId"] == "T2"


def test_full_charge_creates_bill(ctx):
    """充满自动结束：生成账单（25+32=57 元）并更新桩统计。"""
    submit(ctx, "V1", "T", 40)
    ctx.step()
    advance(ctx, hours=4, minutes=1)
    state = ctx.charging_service.query_car_state("V1")
    assert state["status"] == "FINISHED"
    bills = ctx.billing_service.request_bill("V1")
    assert len(bills) == 1
    b = bills[0]
    assert b["chargeAmount"] == 40.0
    assert b["totalChargeFee"] == 25.0
    assert b["totalServiceFee"] == 32.0
    assert b["totalFee"] == 57.0
    pile = ctx.station.find_pile("T1")
    assert pile.total_charge_num == 1
    assert abs(pile.total_capacity - 40.0) < 1e-6
    # 详单分时明细
    detail = ctx.billing_service.request_detailed_list(b["billId"])
    assert [s["kind"] for s in detail["segments"]] == ["valley", "flat"]


def test_next_car_starts_after_finish(ctx):
    """前车充满出队后，队内下一辆自动开始充电。"""
    submit(ctx, "V1", "F", 30)   # 1h
    ctx.step()
    for i in range(2, 8):        # 填满两个快充桩
        submit(ctx, f"V{i}", "F", 30)
        ctx.step()
    advance(ctx, hours=1, minutes=1)
    # V1 完成，原 V1 所在桩的下一辆开始充电
    s1 = ctx.charging_service.query_car_state("V1")
    assert s1["status"] == "FINISHED"
    charging = [ctx.charging_service.query_car_state(f"V{i}")
                for i in range(2, 8)]
    assert sum(1 for s in charging if s["status"] == "CHARGING") == 2


def test_modify_amount_rules(ctx):
    submit(ctx, "V1", "T", 40)
    ctx.step()  # 充电中
    with pytest.raises(BusinessError):
        ctx.charging_service.modify_amount("V1", 20)
    submit(ctx, "V2", "T", 30)  # 进 T2 排队? 实际被调度充电中
    # 放一辆注定排队的车：T 区塞满后提交
    for i in range(3, 11):
        submit(ctx, f"V{i}", "T", 10)
        ctx.step()
    state = ctx.charging_service.query_car_state("V10")
    assert state["status"] in ("WAITING", "QUEUING")
    ctx.charging_service.modify_amount("V10", 25)
    assert ctx.charging_service.query_car_state("V10")["requestedAmount"] == 25


def test_modify_mode_renumbers_and_requeues(ctx):
    """等候区改模式：换队列尾 + 重新发号。"""
    # 占满快充区
    for i in range(1, 7):
        submit(ctx, f"F{i}", "F", 30)
        ctx.step()
    submit(ctx, "X1", "F", 20)   # 等候区·快充, F7
    submit(ctx, "X2", "F", 20)   # 等候区·快充, F8
    s = ctx.charging_service.query_car_state("X1")
    assert s["status"] == "WAITING" and s["queueNumber"] == "F7"
    ctx.charging_service.modify_mode("X1", "T")
    s = ctx.charging_service.query_car_state("X1")
    assert s["queueNumber"] == "T1"
    ctx.step()  # 慢充区有空位，立即被调度
    assert ctx.charging_service.query_car_state("X1")["pileId"] in ("T1", "T2", "T3")


def test_cancel_waiting_and_charging(ctx):
    """取消：等候区直接移除；充电中按已充电量结算。"""
    submit(ctx, "V1", "T", 40)
    ctx.step()
    advance(ctx, hours=1)  # 已充 10 度（06:00–07:00 谷时）
    result = ctx.charging_service.cancel("V1")
    assert result["status"] == "FINISHED"
    b = result["bill"]
    assert b["chargeAmount"] == 10.0
    assert b["totalChargeFee"] == 4.0     # 10×0.4
    assert b["totalServiceFee"] == 8.0    # 10×0.8
    # 等候区取消
    for i in range(2, 12):
        submit(ctx, f"V{i}", "T", 10)
        ctx.step()
    waiting = [f"V{i}" for i in range(2, 12)
               if ctx.charging_service.query_car_state(f"V{i}")["status"] == "WAITING"]
    assert waiting
    ctx.charging_service.cancel(waiting[0])
    assert ctx.charging_service.query_car_state(waiting[0])["status"] == "CANCELED"
