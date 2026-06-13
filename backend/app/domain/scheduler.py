"""调度器 Scheduler（纯虚构领域服务）：选桩与求最优算法。

- assign_pile：调度策略——被调度车辆完成充电所需时间（等待时长+自己充电时长）最短。
- min_total_time_assign：Bonus 单次/批量调度，枚举车→桩分配方案使总充电时长最短；
  跨模式搭配按设计「罚无穷」（计入 ∞ 而非显式过滤），由 select_min 自动排除。
"""
from __future__ import annotations

from datetime import datetime
from math import inf
from typing import Dict, List, Optional, Tuple

from .models import ChargingPile, ChargingRequest

# 枚举规模上限：超过则退回按排队号贪心（验收/演示规模远小于该值）
ENUM_CAR_LIMIT = 10


class Scheduler:

    def assign_pile(self, cr: ChargingRequest, piles: List[ChargingPile],
                    now: datetime) -> Optional[ChargingPile]:
        """调度策略（spec：被调度车辆"完成充电所需时间=等待时长+自己充电时长"最短）：
        在全部同模式运行桩中选完成时间最短的桩；若该最优桩当前车位已满，则本车继续等待
        （不退而求其次塞进次优空桩，否则会偏离"完成时间最短"目标，验收"调度结束"时刻随之滞后）。
        无可接桩返回 None。"""
        candidates = [p for p in piles if p.mode is cr.mode and p.is_open_for_dispatch()]
        if not candidates:
            return None
        best = min(candidates, key=lambda p: (
            p.estimate_wait_time(now) + p.calc_charge_duration(cr.requested_amount),
            p.pile_id,
        ))
        return best if not best.queue.is_full() else None

    def collect_uncharged(self, piles: List[ChargingPile]) -> List[ChargingRequest]:
        """收集所有“尚未开始充电”的排队车辆，同时从原桩出队、释放原车位
        （保证不会出现一车占两位）。正在充电的车不动。"""
        collected: List[ChargingRequest] = []
        for pile in piles:
            for cr in pile.queue.get_queuing_cars():
                pile.remove_from_queue(cr)
                cr.pile_id = None
                collected.append(cr)
        return collected

    def sort_by_queue_number(self, cars: List[ChargingRequest]) -> List[ChargingRequest]:
        """按排队号（先来后到）公平排序。"""
        return sorted(cars, key=lambda c: c.queue_seq)

    # ---- Bonus：总充电时长最短 ----
    def min_total_time_assign(self, piles: List[ChargingPile], cars: List[ChargingRequest],
                              now: datetime) -> Optional[List[Tuple[ChargingRequest, ChargingPile]]]:
        """枚举全部分配方案（enumerate_assignments），逐一计算总时长
        （calc_total_charging_time，跨模式记 ∞），选出最小者（select_min）。
        返回 [(car, pile), ...]（保持 cars 给定的先后次序）；无合法方案返回 None。"""
        if not cars or not piles or len(cars) > ENUM_CAR_LIMIT:
            return None
        capacity = {p.pile_id: p.queue.free_spots() for p in piles}
        backlog = {p.pile_id: p.estimate_wait_time(now) for p in piles}
        pile_map = {p.pile_id: p for p in piles}

        best_cost = inf
        best_plan: Optional[List[str]] = None
        n = len(cars)
        chosen: List[str] = []

        def dfs(i: int, cost: float, load: Dict[str, float], cap: Dict[str, int]) -> None:
            nonlocal best_cost, best_plan
            if cost >= best_cost:
                return  # 剪枝：部分代价已不优
            if i == n:
                best_cost, best_plan = cost, list(chosen)
                return
            car = cars[i]
            for p in piles:
                if cap[p.pile_id] <= 0:
                    continue
                # 同模式约束：非法搭配时长为 ∞（罚无穷），等价于跳过该分支
                if p.mode is not car.mode:
                    continue
                charge = p.calc_charge_duration(car.requested_amount)
                wait = backlog[p.pile_id] + load[p.pile_id]
                completion = wait + charge  # 该车完成充电所需总时长
                cap[p.pile_id] -= 1
                load[p.pile_id] += charge
                chosen.append(p.pile_id)
                dfs(i + 1, cost + completion, load, cap)
                chosen.pop()
                load[p.pile_id] -= charge
                cap[p.pile_id] += 1

        dfs(0, 0.0, {pid: 0.0 for pid in capacity}, dict(capacity))
        if best_plan is None:
            return None
        return [(cars[i], pile_map[best_plan[i]]) for i in range(n)]
