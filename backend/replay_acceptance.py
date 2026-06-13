"""验收用例全量回放：把《作业验收用例.xlsx》42 个事件灌入引擎，
逐 30s(模拟时间)单步驱动，输出每个事件时刻的桩位/等候区快照，
并核对表中已给出的样例值与「调度结束」时刻。

用法：python3 replay_acceptance.py [manual|requeue]
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta

from app.context import AppContext
from app.domain.enums import BusinessError, RequestStatus

SIM_DAY = datetime(2026, 6, 11)

# (时刻, 类别, 对象, 类型, 数值)
# A=车辆事件(F/T=提交申请, O=结束/取消) B=桩事件(0=故障,1=恢复) C=修改充电量
EVENTS = [
    ("06:00", "A", "V1", "T", 40), ("06:05", "A", "V2", "T", 30),
    ("06:10", "A", "V3", "F", 100), ("06:15", "A", "V4", "F", 120),
    ("06:20", "A", "V2", "O", 0), ("06:25", "A", "V5", "T", 20),
    ("06:30", "A", "V6", "T", 20), ("06:35", "A", "V7", "F", 110),
    ("06:40", "A", "V8", "T", 20), ("06:45", "A", "V9", "F", 105),
    ("06:50", "A", "V10", "T", 10), ("06:55", "A", "V11", "F", 110),
    ("07:00", "A", "V12", "F", 90), ("07:05", "A", "V13", "F", 110),
    ("07:10", "A", "V14", "F", 95), ("07:15", "A", "V15", "T", 10),
    ("07:20", "A", "V16", "F", 60), ("07:25", "A", "V17", "T", 10),
    ("07:30", "A", "V18", "T", 7.5), ("07:35", "A", "V19", "F", 75),
    ("07:40", "A", "V20", "F", 95), ("07:45", "A", "V21", "F", 95),
    ("07:50", "A", "V22", "F", 70), ("07:55", "A", "V23", "F", 80),
    ("08:00", "A", "V24", "T", 5), ("08:20", "A", "V25", "T", 15),
    ("08:25", "B", "T1", "O", 0), ("08:30", "A", "V26", "T", 20),
    ("08:35", "A", "V27", "T", 25), ("08:50", "B", "F1", "O", 0),
    ("09:00", "A", "V28", "F", 30), ("09:10", "A", "V1", "O", 0),
    ("09:15", "B", "T1", "O", 1), ("09:20", "A", "V27", "O", 0),
    ("09:25", "C", "V21", "O", 35), ("09:30", "A", "V19", "O", 0),
    ("09:35", "A", "V28", "O", 0), ("09:40", "C", "V23", "O", 40),
    ("09:55", "C", "V14", "O", 30), ("09:50", "A", "V29", "T", 30),
    ("10:00", "A", "V30", "T", 10), ("10:50", "B", "F1", "O", 1),
]
EVENTS.sort(key=lambda e: e[0])


def hm(t: str) -> datetime:
    h, m = (int(x) for x in t.split(":"))
    return SIM_DAY.replace(hour=h, minute=m, second=0)


def snapshot(ctx) -> dict:
    now = ctx.clock.now()
    piles = {}
    for p in ctx.station.charging_area.get_all_piles():
        cells = []
        for c in p.queue.get_cars():
            if c.status is RequestStatus.CHARGING:
                est = ctx.billing_service.estimate(c, p, now)
                cells.append(f"({c.car_id},{est['chargedAmount']:.2f},{est['totalFee']:.2f})")
            else:
                cells.append(f"({c.car_id},排队)")
        piles[p.pile_id] = cells
    waiting = [f"({c.car_id},{c.mode.value},{c.requested_amount:.2f})"
               for c in ctx.station.waiting_area.get_all_requests()]
    return {"piles": piles, "waiting": waiting}


def main(policy: str) -> None:
    tmp = tempfile.mkdtemp(prefix=f"replay_{policy}_")
    ctx = AppContext(tmp, db_path=":memory:")
    ctx.clock.set_speed(0)
    ctx.clock.set_time(hm("06:00"))
    ctx.config.data["interruptPolicy"] = policy   # manual / requeue
    assert ctx.config.faultStrategy == "priority"

    errors, applied = [], []
    pending = list(EVENTS)
    t = hm("06:00")
    end_limit = SIM_DAY + timedelta(days=1, hours=8)

    def run_event(ev):
        tag = f"{ev[0]} {ev[1]},{ev[2]},{ev[3]},{ev[4]}"
        try:
            if ev[1] == "A" and ev[3] in ("F", "T"):
                ctx.charging_service.submit_request(ev[2], ev[3], ev[4])
            elif ev[1] == "A":           # O：结束充电/取消
                ctx.charging_service.cancel(ev[2])
            elif ev[1] == "B" and ev[4] == 0:
                ctx.schedule_service.handle_fault(ev[2])
            elif ev[1] == "B":
                ctx.schedule_service.handle_recovery(ev[2])
            elif ev[1] == "C":
                ctx.charging_service.modify_amount(ev[2], ev[4])
            applied.append(tag)
        except BusinessError as e:
            errors.append(f"{tag}  -> 业务错误: {e}")
        except Exception as e:                      # noqa: BLE001
            errors.append(f"{tag}  -> 异常 {type(e).__name__}: {e}")

    snaps = {}
    while t <= end_limit:
        ctx.clock.set_time(t)
        while pending and hm(pending[0][0]) <= t:
            run_event(pending.pop(0))
        ctx.step()
        if t.second == 0 and t.minute % 5 == 0:
            snaps[t.strftime("%H:%M")] = snapshot(ctx)
        active = [r for r in ctx.station.requests.values() if r.status.active]
        if not pending and not active:
            break
        t += timedelta(seconds=30)

    # ---- 输出 ----
    print(f"===== interruptPolicy = {policy} =====")
    print(f"事件执行: {len(applied)}/{len(EVENTS)} 条成功")
    for e in errors:
        print("  [事件失败]", e)

    for key in ("06:00", "06:05", "07:05", "07:10", "07:15"):
        s = snaps.get(key)
        if s:
            print(f"--- {key} ---  ", {k: v for k, v in s["piles"].items()},
                  " 等候区:", "-".join(s["waiting"]) or "空")

    reqs = sorted(ctx.station.requests.values(), key=lambda r: r.submit_time)
    finished_ends = [r.end_time for r in reqs if r.end_time]
    last_end = max(finished_ends) if finished_ends else None
    leftover = [(r.car_id, r.status.value) for r in reqs if r.status.active]
    inter = [(r.car_id, r.status.value) for r in reqs
             if r.status is RequestStatus.INTERRUPTED]
    print("最后一次结束时刻(调度结束):", last_end.strftime("%m-%d %H:%M:%S") if last_end else None)
    print("仍滞留(未终态)车辆:", leftover or "无")
    print("已中断(需重新申请)车辆:", inter or "无")

    # 样例值断言
    s = snaps["06:05"]
    print("核对 06:05 T1 应为 (V1,0.83,1.00):", s["piles"]["T1"],
          " T2 应为 (V2,0.00,0.00):", s["piles"]["T2"])
    for key, want in (("07:05", ["(V13,F,110.00)"]),
                      ("07:10", ["(V13,F,110.00)", "(V14,F,95.00)"]),
                      ("07:15", ["(V13,F,110.00)", "(V14,F,95.00)"])):
        got = snaps[key]["waiting"]
        mark = "OK" if got == want else "MISMATCH"
        print(f"核对 {key} 等候区 {mark}: 期望 {want} 实际 {got}")

    # 全程快照（便于填表）
    print("--- 全程逐事件快照 ---")
    for key in sorted(snaps):
        s = snaps[key]
        if any(s["piles"].values()) or s["waiting"]:
            print(key, " | F1:", "+".join(s["piles"].get("F1", [])) or "-",
                  "| F2:", "+".join(s["piles"].get("F2", [])) or "-",
                  "| T1:", "+".join(s["piles"].get("T1", [])) or "-",
                  "| T2:", "+".join(s["piles"].get("T2", [])) or "-",
                  "| T3:", "+".join(s["piles"].get("T3", [])) or "-",
                  "| 等候:", "-".join(s["waiting"]) or "空")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "requeue")
