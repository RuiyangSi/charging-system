"""控制层 Controller：接收前端/设备请求，参数校验+协议转换，转发 Service（不写业务）。

REST ↔ 系统事件映射：
  ChargingController   POST /charging/request            E_chargingRequest
                       PUT  /charging/amount             Modify_Amount
                       PUT  /charging/mode               Modify_Mode
                       GET  /charging/car-state/{car}    Query_Car_State
                       GET  /charging/charging-state/{car} Query_Charging_State
                       DELETE /charging/request/{car}    取消充电/结束充电
  PileEventController  POST /pile-event/{pile}/start     Start_Charging（设备上报）
                       POST /pile-event/{pile}/end       End_Charging（设备上报）
                       POST /pile-event/{pile}/fault     reportFault（优先级/时间顺序调度）
                       POST /pile-event/{pile}/recover   recoverPile（故障恢复）
  PileController       POST /pile/{pile}/power-on        powerOn
                       PUT  /pile/parameters             setParameters
                       POST /pile/{pile}/run             Start_ChargingPile(runPile)
                       POST /pile/{pile}/power-off       powerOff
                       GET  /pile/state                  Query_PileState
                       GET  /pile/{pile}/queue           Query_QueueState
  BillController       GET  /bill                        Request_Bill
                       GET  /bill/{billId}/detail        Request_DetailedList
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from ..context import get_context
from . import schemas

charging_router = APIRouter(prefix="/charging", tags=["ChargingController"])
pile_event_router = APIRouter(prefix="/pile-event", tags=["PileEventController"])
pile_router = APIRouter(prefix="/pile", tags=["PileController"])
bill_router = APIRouter(prefix="/bill", tags=["BillController"])
user_router = APIRouter(prefix="/user", tags=["User"])


# ============ 用户 ============
@user_router.post("/login")
def login(body: schemas.LoginBody):
    ctx = get_context()
    with ctx.lock:
        user = ctx.user_repo.ensure(body.carId.strip(), body.capacity)
        return {"carId": user["car_id"], "capacity": user["capacity"]}


# ============ ChargingController ============
@charging_router.post("/request")
def submit_request(body: schemas.ChargingRequestBody):
    """E_chargingRequest(car_Id, Request_Amount, Request_Mode)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.submit_request(body.carId, body.mode, body.amount)


@charging_router.put("/amount")
def modify_amount(body: schemas.ModifyAmountBody):
    """Modify_Amount(car_Id, Amount)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.modify_amount(body.carId, body.amount)


@charging_router.put("/mode")
def modify_mode(body: schemas.ModifyModeBody):
    """Modify_Mode(car_Id, Mode)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.modify_mode(body.carId, body.mode)


@charging_router.delete("/request/{car_id}")
def cancel(car_id: str):
    """取消充电（充电中=按已充电量结算并结束）"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.cancel(car_id)


@charging_router.get("/car-state/{car_id}")
def query_car_state(car_id: str):
    """Query_Car_State(car_id)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.query_car_state(car_id)


@charging_router.get("/charging-state/{car_id}")
def query_charging_state(car_id: str):
    """Query_Charging_State(car_id)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.query_charging_state(car_id)


# ============ PileEventController（充电桩设备上报）============
@pile_event_router.post("/{pile_id}/start")
def start_charging(pile_id: str):
    """Start_Charging(car_id, ChargePileNum)：车辆就位接枪，设备上报开始充电"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.start_charging(pile_id)


@pile_event_router.post("/{pile_id}/end")
def end_charging(pile_id: str):
    """End_Charging(car_id, ChargingPileNum)：设备上报充电完成"""
    ctx = get_context()
    with ctx.lock:
        return ctx.charging_service.end_charging(pile_id, reason="full")


@pile_event_router.post("/{pile_id}/fault")
def report_fault(pile_id: str, body: Optional[schemas.FaultBody] = None):
    """reportFault：故障再调度（priority=优先级 / time_order=时间顺序）。
    body 可省略（无请求体即按系统默认策略），便于"最简故障注入"。"""
    ctx = get_context()
    body = body or schemas.FaultBody()
    with ctx.lock:
        rec = ctx.schedule_service.handle_fault(pile_id, body.faultType or "设备故障",
                                                body.strategy)
        return rec.to_dict()


@pile_event_router.post("/{pile_id}/recover")
def recover_pile(pile_id: str):
    """recoverPile：故障恢复 + 趁机整体重排"""
    ctx = get_context()
    with ctx.lock:
        return ctx.schedule_service.handle_recovery(pile_id)


# ============ PileController（管理员运维与监控）============
@pile_router.post("/{pile_id}/power-on")
def power_on(pile_id: str):
    ctx = get_context()
    with ctx.lock:
        return ctx.pile_service.power_on(pile_id)


@pile_router.put("/parameters")
def set_parameters(body: schemas.BillingRuleBody):
    """setParameters：计费规则（三时段电价+服务费）——PileService 委托 BillingService"""
    ctx = get_context()
    with ctx.lock:
        return ctx.pile_service.set_parameters(body.model_dump(exclude_none=True))


@pile_router.get("/parameters")
def get_parameters():
    ctx = get_context()
    with ctx.lock:
        return ctx.billing_service.rule.to_dict()


@pile_router.post("/{pile_id}/run")
def run_pile(pile_id: str):
    """Start_ChargingPile(runPile)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.pile_service.run_pile(pile_id)


@pile_router.post("/{pile_id}/power-off")
def power_off(pile_id: str):
    ctx = get_context()
    with ctx.lock:
        return ctx.pile_service.power_off(pile_id)


@pile_router.get("/state")
def query_pile_state():
    """Query_PileState：全部桩工作状态与累计统计（前端定时刷新）"""
    ctx = get_context()
    with ctx.lock:
        return ctx.pile_service.query_pile_state()


@pile_router.get("/{pile_id}/queue")
def query_queue_state(pile_id: str):
    """Query_QueueState(queuelist)：车辆ID/电池容量/请求电量/排队时长"""
    ctx = get_context()
    with ctx.lock:
        return ctx.pile_service.query_queue_state(pile_id)


# ============ BillController ============
@bill_router.get("")
def request_bill(carId: str, date: str = None):
    """Request_Bill(carId, date)"""
    ctx = get_context()
    with ctx.lock:
        return ctx.billing_service.request_bill(carId, date)


@bill_router.get("/{bill_id}/detail")
def request_detailed_list(bill_id: str):
    """Request_DetailedList(Bill_Id)：分时明细经 bill.get_order() 内存导航"""
    ctx = get_context()
    with ctx.lock:
        return ctx.billing_service.request_detailed_list(bill_id)
