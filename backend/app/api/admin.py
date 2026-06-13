"""管理端聚合接口：监控大屏 overview、统计报表、系统参数、虚拟时钟、重置。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter

from ..config import parse_hms
from ..context import get_context
from ..domain.enums import BusinessError, PileStatus, RequestStatus
from . import schemas

admin_router = APIRouter(prefix="/admin", tags=["Admin"])

# 结构性参数：变更后需重置系统才生效
STRUCTURAL_KEYS = {"FastChargingPileNum", "TrickleChargingPileNum",
                   "ChargingQueueLen", "WaitingAreaSize", "FastPower", "TricklePower"}


@admin_router.get("/overview")
def overview():
    """监控大屏数据：KPI + 桩实时状态 + 等候区/桩队列总表。"""
    ctx = get_context()
    with ctx.lock:
        now = ctx.clock.now()
        station = ctx.station

        # 桩快照：对正在充电的桩附带"当前费用"实时预估（验收抄三元组：车号/已充电量/当前费用）
        piles = []
        for p in station.charging_area.get_all_piles():
            snap = p.snapshot(now)
            crc = p.queue.get_charging_request()
            if crc and snap.get("current"):
                snap["current"]["estimate"] = ctx.billing_service.estimate(crc, p, now)
            piles.append(snap)

        def wait_hours(cr) -> float:
            """排队时长 = 自进入等候区(提交)起经过的时长（Query_QueueState 的 waitTime）。"""
            return round(max((now - cr.submit_time).total_seconds() / 3600.0, 0.0), 2)

        # 等候区 + 桩队列 合并排队总表
        queue_table = []
        for pile in station.charging_area.get_all_piles():
            ahead_h = 0.0
            for cr in pile.queue.get_cars():
                remain = cr.remaining_duration_h(now, pile.power)
                queue_table.append({
                    "queueNumber": cr.queue_number, "carId": cr.car_id,
                    "capacity": cr.capacity,
                    "requestedAmount": round(cr.requested_amount, 2),
                    "modeLabel": cr.mode.label,
                    "location": f"{pile.pile_id} 排队队列" if cr.status is RequestStatus.QUEUING
                                else f"{pile.pile_id} 充电中",
                    "status": cr.status.value, "statusLabel": cr.status.label,
                    "estimateWait": round(ahead_h, 2),
                    "waitTime": wait_hours(cr),
                    "seq": cr.queue_seq,
                })
                ahead_h += remain
        for cr in station.waiting_area.get_all_requests():
            est = ctx.charging_service.estimate_wait_for_waiting(cr, now)
            queue_table.append({
                "queueNumber": cr.queue_number, "carId": cr.car_id,
                "capacity": cr.capacity,
                "requestedAmount": round(cr.requested_amount, 2),
                "modeLabel": cr.mode.label,
                "location": f"等候区·{cr.mode.label}",
                "status": cr.status.value, "statusLabel": cr.status.label,
                "estimateWait": est,
                "waitTime": wait_hours(cr),
                "seq": cr.queue_seq,
            })

        # 本场累计（而非按日历"今日"）：模拟时钟跨午夜后白天数据不会从 KPI 消失
        totals = ctx.order_repo.totals_all()
        waiting_count = station.waiting_area.get_total_waiting_count()
        pile_queue_count = sum(len(p.queue.get_queuing_cars())
                               for p in station.charging_area.get_all_piles())
        charging = [p.pile_id for p in station.charging_area.get_all_piles()
                    if p.queue.get_charging_request()]
        return {
            "clock": ctx.clock.snapshot(),
            "kpis": {
                "onlinePiles": sum(1 for p in station.charging_area.get_all_piles()
                                   if p.status is PileStatus.RUNNING),
                "totalPiles": len(piles),
                "chargingCount": len(charging),
                "chargingPiles": charging,
                "queueCount": waiting_count + pile_queue_count,
                "waitingCount": waiting_count,
                "pileQueueCount": pile_queue_count,
                "todayCapacity": round(totals["capacity"], 2),
                "todayRevenue": round(totals["fee"], 2),
                "todayNum": totals["num"],
            },
            "piles": piles,
            "queueTable": queue_table,
            "waitingArea": {
                "capacity": station.waiting_area.capacity,
                "count": waiting_count,
            },
            "schedule": {
                "paused": ctx.schedule_service.dispatch_paused,
                "dispatchMode": ctx.config.dispatchMode,
                "faultStrategy": ctx.config.faultStrategy,
                "interruptPolicy": ctx.config.interruptPolicy,
            },
        }


@admin_router.get("/report")
def report(period: str = "day", date: str = None):
    """统计报表：时间(日/周/月) × 充电桩 → 次数/时长/电量/充电费/服务费/总费用。"""
    ctx = get_context()
    with ctx.lock:
        now = ctx.clock.now()
        end = datetime.strptime(date, "%Y-%m-%d") if date else now
        if period == "week":
            start = end - timedelta(days=6)
        elif period == "month":
            start = end.replace(day=1)
        else:
            period, start = "day", end
        d0, d1 = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        rows = ctx.order_repo.stats_by_pile(d0, d1)
        # 无订单的桩也要在报表中出现
        known = {r["pile_id"] for r in rows}
        for p in ctx.station.charging_area.get_all_piles():
            if p.pile_id not in known:
                rows.append({"pile_id": p.pile_id, "charge_num": 0, "charge_time": 0,
                             "capacity": 0, "charge_fee": 0, "service_fee": 0, "total_fee": 0})
        rows.sort(key=lambda r: r["pile_id"])
        table = [{
            "pileId": r["pile_id"],
            "chargeNum": r["charge_num"] or 0,
            "chargeTime": round(r["charge_time"] or 0, 2),
            "capacity": round(r["capacity"] or 0, 2),
            "chargeFee": round(r["charge_fee"] or 0, 2),
            "serviceFee": round(r["service_fee"] or 0, 2),
            "totalFee": round(r["total_fee"] or 0, 2),
        } for r in rows]
        chart_start = (end - timedelta(days=6)).strftime("%Y-%m-%d")
        daily = ctx.order_repo.daily_totals(chart_start, d1)
        return {
            "period": period, "dateFrom": d0, "dateTo": d1,
            "table": table,
            "totals": {
                "chargeNum": sum(t["chargeNum"] for t in table),
                "chargeTime": round(sum(t["chargeTime"] for t in table), 2),
                "capacity": round(sum(t["capacity"] for t in table), 2),
                "chargeFee": round(sum(t["chargeFee"] for t in table), 2),
                "serviceFee": round(sum(t["serviceFee"] for t in table), 2),
                "totalFee": round(sum(t["totalFee"] for t in table), 2),
            },
            "daily": [{"date": d["date"], "capacity": round(d["capacity"] or 0, 2),
                       "fee": round(d["fee"] or 0, 2), "num": d["num"]} for d in daily],
        }


@admin_router.get("/faults")
def list_faults():
    ctx = get_context()
    with ctx.lock:
        return ctx.fault_repo.list_all()


@admin_router.get("/config")
def get_config():
    ctx = get_context()
    with ctx.lock:
        return ctx.config.as_dict()


@admin_router.put("/config")
def update_config(body: schemas.ConfigBody):
    ctx = get_context()
    with ctx.lock:
        patch = body.model_dump(exclude_none=True)
        if "dispatchMode" in patch and patch["dispatchMode"] not in (
                "default", "single_optimal", "batch_optimal"):
            raise BusinessError("dispatchMode 须为 default/single_optimal/batch_optimal")
        if "faultStrategy" in patch and patch["faultStrategy"] not in ("priority", "time_order"):
            raise BusinessError("faultStrategy 须为 priority/time_order")
        if "interruptPolicy" in patch and patch["interruptPolicy"] not in ("manual", "requeue"):
            raise BusinessError("interruptPolicy 须为 manual/requeue")
        ctx.config.update(patch)
        return {
            "config": ctx.config.as_dict(),
            "requiresReset": bool(STRUCTURAL_KEYS & patch.keys()),
        }


@admin_router.get("/clock")
def get_clock():
    return get_context().clock.snapshot()


@admin_router.put("/clock")
def set_clock(body: schemas.ClockBody):
    ctx = get_context()
    with ctx.lock:
        if body.speed is not None:
            ctx.clock.set_speed(float(body.speed))
        if body.time:
            t = body.time.strip()
            now = ctx.clock.now()
            if " " in t:  # "YYYY-MM-DD HH:MM:SS"
                dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            else:         # "HH:MM" 或 "HH:MM:SS"（容错解析，非法格式→400）
                h, m, s = parse_hms(t)
                dt = now.replace(hour=h, minute=m, second=s, microsecond=0)
            ctx.clock.set_time(dt)
        return ctx.clock.snapshot()


@admin_router.post("/reset")
def reset(body: schemas.ResetBody):
    """系统重置：重建充电站（按当前参数）+ 时钟归位（验收开跑前使用）。"""
    ctx = get_context()
    ctx.reset(wipe_history=body.wipeHistory)
    return {"ok": True, "clock": ctx.clock.snapshot()}


@admin_router.get("/meta")
def meta():
    """公共元信息（用户端展示用）：桩配置 + 当前计费规则 + 时钟。"""
    ctx = get_context()
    with ctx.lock:
        c = ctx.config
        return {
            "fastPileNum": c.FastChargingPileNum,
            "tricklePileNum": c.TrickleChargingPileNum,
            "fastPower": c.FastPower,
            "tricklePower": c.TricklePower,
            "queueLen": c.ChargingQueueLen,
            "waitingAreaSize": c.WaitingAreaSize,
            "rule": ctx.billing_service.rule.to_dict(),
            "clock": ctx.clock.snapshot(),
        }
