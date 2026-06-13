# 智能充电桩调度计费系统（代码实现）

> BUPT 软件工程大作业 · 2023211301_G6
> 后端 Python **FastAPI** ＋ 前端 **React (Vite)**，按《概要设计》四层架构与 DESIGN_BIBLE 命名实现，
> 覆盖全部 **15 个标黄系统事件 ＋ 3 个故障调度场景 ＋ 2 个 Bonus 扩展调度**。

---

## 一、快速开始

### 方式 A：单端口运行（推荐演示/验收用）

前端已构建到 `frontend/dist`，由后端直接托管，**只需启动后端**：

```bash
cd backend
pip3 install -r requirements.txt
python3 -m uvicorn app.main:app --port 8000
```

浏览器打开 <http://127.0.0.1:8000> —— 登录页可分别进入**用户客户端**与**管理员控制台**。
（8000 被占用时换端口即可，如 `--port 8001`，前端用相对路径请求 API，不受影响）

### 方式 B：前后端分离开发

```bash
# 终端 1：后端（热重载）
cd backend && python3 -m uvicorn app.main:app --reload --port 8000

# 终端 2：前端（Vite 热更新，自动代理 /api → 8000）
cd frontend && npm install && npm run dev        # http://127.0.0.1:5173
# 后端不在 8000 时：BACKEND=http://127.0.0.1:8001 npm run dev
```

修改前端后重新生成单端口部署物：`cd frontend && npm run build`

### 运行测试

```bash
cd backend && python3 -m pytest tests/ -v        # 25 个用例：计费/调度/故障/Bonus
```

---

## 二、目录结构（四层架构 ↔ 代码）

```
charging-system/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口 + 模拟引擎后台任务 + SPA 托管
│   │   ├── context.py               # AppContext：四层装配 + 引擎单步 step()
│   │   ├── config.py                # 系统参数（与验收用例参数名一致，可改）
│   │   ├── sim_clock.py             # 虚拟时钟（验收比例尺 1:10）
│   │   ├── api/                     # ―― 控制层 Controller（只转发，不写业务）
│   │   │   ├── controllers.py       #   Charging/PileEvent/Pile/Bill Controller
│   │   │   ├── admin.py             #   监控大屏/报表/参数/时钟/重置
│   │   │   └── schemas.py           #   请求体校验
│   │   ├── services/                # ―― 业务层 Service（用例编排+创建实例）
│   │   │   ├── charging_service.py  #   系统事件 1–7
│   │   │   ├── schedule_service.py  #   叫号 + 故障调度 + Bonus
│   │   │   ├── pile_service.py      #   系统事件 10–15
│   │   │   └── billing_service.py   #   结算/账单/计费规则
│   │   ├── domain/                  # ―― 领域层 Domain（信息专家）
│   │   │   ├── models.py            #   ChargingStation/WaitingArea/ChargingPile/
│   │   │   │                        #   PileQueue/ChargingRequest/FaultRecord
│   │   │   ├── scheduler.py         #   Scheduler：选桩 + 求最优（罚∞）
│   │   │   ├── billing.py           #   BillingEngine/BillingRule/Order/Bill
│   │   │   └── enums.py
│   │   └── db.py                    # ―― 持久层 Repository（SQLite）
│   └── tests/                       # pytest（含验收用例数值核对）
└── frontend/
    └── src/
        ├── pages/Login.jsx          # 入口（用户/管理员）
        ├── pages/user/              # 用户端（浅色能源绿，移动栅格）
        │   ├── ChargePage.jsx       #   充电申请/排队状态/充电状态
        │   └── BillsPage.jsx        #   账单 + 分时详单
        └── pages/admin/             # 管理员端（深色控制台）
            ├── MonitorPage.jsx      #   监控大屏（KPI/桩状态/队列 + 时钟控制）
            ├── OpsPage.jsx          #   运维（上电/运行/关闭/故障注入恢复/策略）
            ├── RulesPage.jsx        #   分时计费规则 setParameters
            ├── ReportsPage.jsx      #   统计报表（日/周/月 × 桩）
            ├── FaultsPage.jsx       #   FaultRecord 档案
            └── SettingsPage.jsx     #   验收参数 + 虚拟时钟 + 重置
```

说明：设计中的 `ParkingSpot/occupySpot` 由 `PileQueue` 的槽位承载（每桩 M 个车位，队首即充电位）；
其余类名/方法名与 DESIGN_BIBLE 一致（Python snake_case 形式）。

---

## 三、系统事件 ↔ REST API 映射

| # | 系统事件 | 方法与路径 | 触发者 |
|---|---|---|---|
| 1 | E_chargingRequest 提交充电申请 | `POST /api/charging/request` | 用户 |
| 2 | Modify_Amount 修改充电量 | `PUT /api/charging/amount` | 用户 |
| 3 | Modify_Mode 修改充电模式 | `PUT /api/charging/mode` | 用户 |
| 4 | Query_Car_State 查看排队状态 | `GET /api/charging/car-state/{carId}` | 用户 |
| 5 | Start_Charging 开始充电 | `POST /api/pile-event/{pileId}/start` | 充电桩(设备)¹ |
| 6 | Query_Charging_State 查看充电状态 | `GET /api/charging/charging-state/{carId}` | 用户 |
| 7 | End_Charging 结束充电 | `POST /api/pile-event/{pileId}/end`；用户提前结束=取消接口 | 设备¹ / 用户 |
| — | 取消充电 | `DELETE /api/charging/request/{carId}` | 用户 |
| 8 | Request_Bill 查看账单 | `GET /api/bill?carId=&date=` | 用户 |
| 9 | Request_DetailedList 查看详单 | `GET /api/bill/{billId}/detail` | 用户 |
| 10 | powerOn 上电 | `POST /api/pile/{pileId}/power-on` | 管理员 |
| 11 | setParameters 设置计费参数 | `PUT /api/pile/parameters` | 管理员 |
| 12 | Start_ChargingPile 运行充电桩 | `POST /api/pile/{pileId}/run` | 管理员 |
| 13 | powerOff 关闭充电桩 | `POST /api/pile/{pileId}/power-off` | 管理员 |
| 14 | Query_PileState 查看桩状态 | `GET /api/pile/state`（前端每秒刷新） | 管理员 |
| 15 | Query_QueueState 查看队列 | `GET /api/pile/{pileId}/queue` | 管理员 |
| 16/17 | reportFault 故障（优先级/时间顺序） | `POST /api/pile-event/{pileId}/fault` `{strategy}` | 设备¹ |
| 18 | recoverPile 故障恢复 | `POST /api/pile-event/{pileId}/recover` | 设备¹ |
| 19/20 | singleDispatch / batchDispatch（Bonus） | 系统内部自动触发，`dispatchMode` 切换 | 系统 |

¹ 设备事件由**后台模拟引擎**自动上报（车辆就位自动开充、充满自动结束）；
管理员端「注入故障/故障恢复」按钮即模拟设备上报，便于演示。

---

## 四、验收指引

**参数**（管理员端 → 参数设置；与《作业验收用例·测试说明》参数名一致）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| FastChargingPileNum / TrickleChargingPileNum | 2 / 3 | 快/慢充桩数 |
| ChargingQueueLen (M) | 3 | 每桩车位数（含充电位） |
| WaitingAreaSize (N) | 10 | 等候区容量 |
| 快充/慢充功率 | 30 / 10 度/h | 验收值（概要设计假设慢充 7，可改） |
| 电价 | 峰 1.0 / 平 0.7 / 谷 0.4，服务费 0.8 | 管理员端「计费规则」可改 |

**虚拟时钟**：默认起始 06:00、×10 倍速（验收比例尺 1:10，现实 30s=系统 5min）。
监控大屏右上角可：调倍速/暂停、设置时间、**重置系统**（清空数据+时钟归位，开跑前点一次）。

**故障调度**：验收默认**优先级调度**（等候区停止叫号 → 优先调度坏桩队列车辆 → 恢复叫号）。
策略在「运维管理」切换；充电中被打断的车辆**默认按「部分计费 + 剩余电量最高优先重新调度续充」**
（`interruptPolicy=requeue`，对应验收用例中被打断的车随后仍能正常结束充电），
也可切回概要设计的「部分计费 + 置已中断 + 由用户重新申请」（`manual`）。

**调度口径（与《作业验收用例》对齐）**：
- 选桩 = 在全部同模式运行桩中选「等待时长 + 自己充电时长」最短者；若该最优桩当前车位已满则本车**继续等待**该桩（不退而求其次塞进次优空桩）。据此回放 42 个验收事件，「调度结束」时刻 = 次日 **01:35**，与验收表「1:35+1」一致。
- 等候区容量 N 为**标称展示值、不硬性拒绝**（验收用例峰值排队会超过 N，原始需求亦为「可容纳任意数量车辆」）；超额车辆按到达先后继续排队。
- 全量回放核对脚本：`python3 replay_acceptance.py`（逐事件输出桩位/等候区快照，断言样例格与调度结束时刻）。

**计费正确性**（已用单元测试锁定验收样例）：
慢充 V1 06:00 充 40 度 → 06:05 显示 (0.83 度, ¥1.00)；10:00 充满出账 ¥57.00
（谷 10×0.4 + 平 30×0.7 = 25 充电费 + 40×0.8 = 32 服务费）。账单的合计 = 已取整充电费 + 已取整服务费，
分时明细各段费用之和 = 充电费小计（无 0.01 错位）。

**系统重置**＝出厂级：清空请求/账单/故障**并把计费规则恢复默认费率**（彩排改过价目不会带入正式验收）。

---

## 五、关键设计还原（与概要设计一致）

- **GRASP 分层**：Controller 只转发；Service 编排用例并创建实例（ChargingService 建
  ChargingRequest、BillingService 建 Order/Bill、ScheduleService 建 FaultRecord）；
  领域对象信息专家（入队问队列、算时长问桩、选桩问 Scheduler、算费问 BillingEngine）。
- **调度策略**：被调度车辆完成充电所需时间（等待+自充）最短；`Scheduler.assign_pile`。
- **故障三场景**共用「暂停叫号 → 重排 → 恢复叫号」骨架；优先级=只动坏桩车辆、
  安置不下**插回等候区队首**；时间顺序=收集同类型未充车辆按**排队号**公平重排（充电中不动）。
- **关桩**（powerOff）：排队车按原序回等候区**队首**；充电中车辆**延迟关闭**（充完自动关桩）。
- **Bonus**：单次/批量调度枚举分配方案使总充电时长最短，跨模式搭配**罚 ∞** 由 select_min
  自动排除；批量调度仅当「等候区车数 == 空位总数」触发（设计 Alt[m==n]）。
- **账单查询**：按 carId+date 走 `BillRepository`（外部检索条件走仓储）；
  详单经 `bill.get_order()` 内存导航（顺聚合关系），与设计的「事件 8 vs 9」区分一致。
