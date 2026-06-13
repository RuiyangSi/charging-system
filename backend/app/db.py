"""持久层 Repository（SQLite）。

仓储命名对齐《DESIGN_BIBLE》：ChargingRequestRepository / OrderRepository /
BillRepository(findByBillId/findByCarAndDate) / FaultRepository / BillingRuleRepository。
账单查询只经 BillRepository；订单详单经 bill.get_order() 内存导航（查询用例不经 OrderRepository）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import List, Optional

from .domain.billing import Bill, BillingRule, ChargingOrder
from .domain.models import ChargingRequest, FaultRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  car_id TEXT PRIMARY KEY,
  capacity REAL NOT NULL DEFAULT 60,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS requests (
  request_id TEXT PRIMARY KEY,
  car_id TEXT, mode TEXT, requested_amount REAL, status TEXT,
  queue_number TEXT, queue_seq INTEGER, pile_id TEXT,
  submit_time TEXT, modify_time TEXT, charging_start_time TEXT,
  end_time TEXT, actual_amount REAL
);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY,
  car_id TEXT, pile_id TEXT, mode TEXT, amount REAL, duration_h REAL,
  start_time TEXT, end_time TEXT,
  charge_fee REAL, service_fee REAL, total_fee REAL,
  segments_json TEXT, created_date TEXT
);
CREATE TABLE IF NOT EXISTS bills (
  bill_id TEXT PRIMARY KEY,
  order_id TEXT, car_id TEXT, date TEXT, bill_type TEXT
);
CREATE TABLE IF NOT EXISTS faults (
  fault_id TEXT PRIMARY KEY,
  pile_id TEXT, fault_type TEXT, strategy TEXT,
  fault_time TEXT, recover_time TEXT,
  interrupted_json TEXT, queued_json TEXT, plan_json TEXT
);
CREATE TABLE IF NOT EXISTS billing_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_json TEXT, created_at TEXT
);
"""


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S") if s else None


def _s(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


class Database:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql: str, params=()) -> List[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def clear_runtime_tables(self) -> None:
        """系统重置：清空业务数据 + 计费规则（使重置后计费规则回到验收默认值，
        避免彩排期间 setParameters 改过的费率静默带入正式验收）。保留 users 便于登录。"""
        with self.lock:
            for t in ("requests", "orders", "bills", "faults", "billing_rules"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def ensure(self, car_id: str, capacity: Optional[float] = None) -> dict:
        row = self.db.query("SELECT * FROM users WHERE car_id=?", (car_id,))
        if row:
            if capacity is not None:
                self.db.execute("UPDATE users SET capacity=? WHERE car_id=?", (capacity, car_id))
            return self.get(car_id)
        self.db.execute("INSERT INTO users(car_id, capacity, created_at) VALUES(?,?,?)",
                        (car_id, capacity if capacity is not None else 60.0,
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        return self.get(car_id)

    def get(self, car_id: str) -> Optional[dict]:
        rows = self.db.query("SELECT * FROM users WHERE car_id=?", (car_id,))
        return dict(rows[0]) if rows else None


class ChargingRequestRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, cr: ChargingRequest) -> None:
        self.db.execute(
            """INSERT INTO requests(request_id, car_id, mode, requested_amount, status,
                 queue_number, queue_seq, pile_id, submit_time, modify_time,
                 charging_start_time, end_time, actual_amount)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(request_id) DO UPDATE SET
                 mode=excluded.mode, requested_amount=excluded.requested_amount,
                 status=excluded.status, queue_number=excluded.queue_number,
                 queue_seq=excluded.queue_seq, pile_id=excluded.pile_id,
                 modify_time=excluded.modify_time,
                 charging_start_time=excluded.charging_start_time,
                 end_time=excluded.end_time, actual_amount=excluded.actual_amount""",
            (cr.request_id, cr.car_id, cr.mode.value, cr.requested_amount, cr.status.value,
             cr.queue_number, cr.queue_seq, cr.pile_id, _s(cr.submit_time), _s(cr.modify_time),
             _s(cr.charging_start_time), _s(cr.end_time), cr.actual_amount))

    def find_by_car_id(self, car_id: str) -> List[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM requests WHERE car_id=? ORDER BY submit_time DESC", (car_id,))]

    def cancel_orphans(self) -> int:
        """启动时把上次进程残留的非终态请求标记为已取消（运行时内存不会被重建，
        这些行已无对应内存对象，否则会成为永久"充电中/排队中"僵尸）。返回清理条数。"""
        cur = self.db.execute(
            "UPDATE requests SET status='CANCELED' "
            "WHERE status IN ('WAITING','QUEUING','CHARGING')")
        return cur.rowcount


class OrderRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, order: ChargingOrder) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO orders(order_id, car_id, pile_id, mode, amount,
                 duration_h, start_time, end_time, charge_fee, service_fee, total_fee,
                 segments_json, created_date)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order.order_id, order.car_id, order.pile_id, order.mode, order.amount,
             order.duration_h, _s(order.start_time), _s(order.end_time),
             order.charge_fee, order.service_fee, order.total_fee,
             json.dumps(order.segments, ensure_ascii=False),
             order.end_time.strftime("%Y-%m-%d")))

    def find_by_car_and_date(self, car_id: str, date: Optional[str] = None) -> List[dict]:
        if date:
            rows = self.db.query(
                "SELECT * FROM orders WHERE car_id=? AND created_date=? ORDER BY end_time",
                (car_id, date))
        else:
            rows = self.db.query(
                "SELECT * FROM orders WHERE car_id=? ORDER BY end_time", (car_id,))
        return [dict(r) for r in rows]

    def stats_by_pile(self, date_from: str, date_to: str) -> List[dict]:
        """统计报表：按桩聚合 [date_from, date_to] 区间的订单。"""
        rows = self.db.query(
            """SELECT pile_id,
                      COUNT(*)            AS charge_num,
                      SUM(duration_h)     AS charge_time,
                      SUM(amount)         AS capacity,
                      SUM(charge_fee)     AS charge_fee,
                      SUM(service_fee)    AS service_fee,
                      SUM(total_fee)      AS total_fee
                 FROM orders
                WHERE created_date BETWEEN ? AND ?
                GROUP BY pile_id ORDER BY pile_id""",
            (date_from, date_to))
        return [dict(r) for r in rows]

    def daily_totals(self, date_from: str, date_to: str) -> List[dict]:
        rows = self.db.query(
            """SELECT created_date AS date, SUM(amount) AS capacity, SUM(total_fee) AS fee,
                      COUNT(*) AS num
                 FROM orders WHERE created_date BETWEEN ? AND ?
                GROUP BY created_date ORDER BY created_date""",
            (date_from, date_to))
        return [dict(r) for r in rows]

    def totals_of_date(self, date: str) -> dict:
        rows = self.db.query(
            """SELECT COALESCE(SUM(amount),0) AS capacity, COALESCE(SUM(total_fee),0) AS fee,
                      COUNT(*) AS num FROM orders WHERE created_date=?""", (date,))
        return dict(rows[0])

    def totals_all(self) -> dict:
        """本场累计（自上次重置以来全部订单）。模拟时钟跨午夜后，按日聚合会让白天数据
        从"今日"KPI 消失，故监控大屏改用本场累计，避免演示尾声 KPI 突然清零。"""
        rows = self.db.query(
            """SELECT COALESCE(SUM(amount),0) AS capacity, COALESCE(SUM(total_fee),0) AS fee,
                      COUNT(*) AS num FROM orders""")
        return dict(rows[0])


class BillRepository:
    def __init__(self, db: Database, order_repo: OrderRepository):
        self.db = db
        self.order_repo = order_repo

    def count_by_date(self, date: str) -> int:
        rows = self.db.query("SELECT COUNT(*) AS n FROM bills WHERE date=?", (date,))
        return rows[0]["n"]

    def save(self, bill: Bill) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO bills(bill_id, order_id, car_id, date, bill_type) VALUES(?,?,?,?,?)",
            (bill.bill_id, bill.order.order_id, bill.order.car_id, bill.date, bill.bill_type))

    def _row_to_dict(self, row) -> Optional[dict]:
        orders = self.db.query("SELECT * FROM orders WHERE order_id=?", (row["order_id"],))
        if not orders:
            return None
        o = dict(orders[0])
        return {
            "billId": row["bill_id"],
            "carId": o["car_id"],
            "date": row["date"],
            "pileId": o["pile_id"],
            "mode": o["mode"],
            "billType": row["bill_type"],
            "chargeAmount": round(o["amount"], 2),
            "chargeDuration": round(o["duration_h"], 2),
            "startTime": o["start_time"],
            "endTime": o["end_time"],
            "totalChargeFee": round(o["charge_fee"], 2),
            "totalServiceFee": round(o["service_fee"], 2),
            "totalFee": round(o["total_fee"], 2),
            "segments": json.loads(o["segments_json"] or "[]"),
        }

    def find_by_bill_id(self, bill_id: str) -> Optional[dict]:
        rows = self.db.query("SELECT * FROM bills WHERE bill_id=?", (bill_id,))
        return self._row_to_dict(rows[0]) if rows else None

    def find_by_car_and_date(self, car_id: str, date: Optional[str] = None) -> List[dict]:
        if date:
            rows = self.db.query(
                "SELECT * FROM bills WHERE car_id=? AND date=? ORDER BY bill_id DESC",
                (car_id, date))
        else:
            rows = self.db.query(
                "SELECT * FROM bills WHERE car_id=? ORDER BY bill_id DESC", (car_id,))
        return [d for d in (self._row_to_dict(r) for r in rows) if d]


class FaultRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, rec: FaultRecord) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO faults(fault_id, pile_id, fault_type, strategy,
                 fault_time, recover_time, interrupted_json, queued_json, plan_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (rec.fault_id, rec.pile_id, rec.fault_type, rec.strategy,
             _s(rec.fault_time), _s(rec.recover_time),
             json.dumps(rec.interrupted, ensure_ascii=False),
             json.dumps(rec.queued, ensure_ascii=False),
             json.dumps(rec.plan, ensure_ascii=False)))

    def list_all(self) -> List[dict]:
        rows = self.db.query("SELECT * FROM faults ORDER BY fault_time DESC")
        out = []
        for r in rows:
            out.append({
                "faultId": r["fault_id"], "pileId": r["pile_id"],
                "faultType": r["fault_type"], "strategy": r["strategy"],
                "strategyLabel": "优先级调度" if r["strategy"] == "priority" else "时间顺序调度",
                "faultTime": r["fault_time"], "recoverTime": r["recover_time"],
                "interrupted": json.loads(r["interrupted_json"] or "[]"),
                "queued": json.loads(r["queued_json"] or "[]"),
                "plan": json.loads(r["plan_json"] or "[]"),
            })
        return out

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM faults")[0]["n"]


class BillingRuleRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_current(self) -> Optional[BillingRule]:
        rows = self.db.query("SELECT rule_json FROM billing_rules ORDER BY id DESC LIMIT 1")
        if not rows:
            return None
        return BillingRule.from_dict(json.loads(rows[0]["rule_json"]))

    def save(self, rule: BillingRule) -> None:
        self.db.execute("INSERT INTO billing_rules(rule_json, created_at) VALUES(?,?)",
                        (json.dumps(rule.to_dict(), ensure_ascii=False),
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
