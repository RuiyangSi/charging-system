# 智能充电桩系统快速启动与验收表格生成

本文档用于快速启动系统，并说明如何根据作业验收样例 Excel 自动回放事件、填充测试结果。

## 1. 环境准备

项目后端使用 Python + FastAPI，前端使用 React + Vite。

推荐使用已经配置好的 Conda 环境：

```powershell
conda activate my_env
```

后端依赖文件位于：

```text
backend/requirements.txt
```

如果后端依赖缺失，可执行：

```powershell
cd backend
pip install -r requirements.txt
```

前端依赖文件位于：

```text
frontend/package.json
```

如果前端依赖缺失，可执行：

```powershell
cd frontend
npm install
```

## 2. 快速启动系统

### 启动后端

在项目根目录下执行：

```powershell
cd backend
conda activate my_env
python -m uvicorn app.main:app --port 8000
```

后端地址：

```text
http://127.0.0.1:8000
```

### 启动前端开发服务

另开一个终端，在项目根目录下执行：

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

如果 `npm run dev -- --host ...` 在本机参数解析异常，可以直接使用：

```powershell
cd frontend
npx vite --host 127.0.0.1 --port 5173
```

前端页面地址：

```text
http://127.0.0.1:5173
```

管理员监控页：

```text
http://127.0.0.1:5173/admin/monitor
```

用户端页面：

```text
http://127.0.0.1:5173/user/charge
```

## 3. 单端口演示方式

如果希望只启动后端，并由后端托管前端静态页面，需要先构建前端：

```powershell
cd frontend
npm run build
```

然后启动后端：

```powershell
cd backend
conda activate my_env
python -m uvicorn app.main:app --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000
```

## 4. 作业验收 Excel 文件

当前验收样例文件位于项目根目录：

```text
副本作业验收用例.xlsx
```

该表中事件格式为：

```text
(事件类型, 对应id, 充电类型, 数值)
```

事件类型说明：

```text
A = Apply，用户提交/取消充电请求
B = Breakdown，充电桩故障/恢复
C = Change，修改充电请求
```

示例：

```text
(A,V1,T,40)   V1 发起慢充，请求 40 度
(A,V2,O,0)    V2 取消/结束充电
(B,T1,O,0)    T1 慢充桩故障
(B,T1,O,1)    T1 慢充桩恢复
(C,V21,O,35)  V21 不改充电类型，将请求电量改为 35 度
```

## 5. 自动回放并填充验收表格

在项目根目录执行：

```powershell
conda activate my_env
python scripts\fill_excel_acceptance_table.py
```

该脚本会：

1. 读取 `副本作业验收用例.xlsx` 中的 42 条验收事件。
2. 按事件时间依次回放系统行为。
3. 将每个时刻的充电桩状态写回 Excel。
4. 将等候区车辆队列写回 Excel。
5. 在备注列记录执行失败原因。
6. 更新“调度结束”时间。

填充后的文件仍为：

```text
副本作业验收用例.xlsx
```

脚本会自动创建备份：

```text
副本作业验收用例.before_fill.xlsx
```

如果填错或需要恢复原始表格，可以使用备份文件。

## 6. 导出详细测试结果

如果需要把每个事件时刻的完整结果导出为单独文件，可执行：

```powershell
conda activate my_env
python scripts\export_excel_replay_results.py
```

输出文件位于：

```text
output/
```

主要文件包括：

```text
output/excel_replay_results.xlsx
output/excel_replay_results.json
output/excel_replay_operations.csv
output/excel_replay_snapshots.csv
output/excel_replay_pile_vehicles.csv
output/excel_replay_waiting_vehicles.csv
```

其中：

```text
Operations       每条事件及对应系统操作
Snapshots        每个事件时刻的五个充电桩和等候区总览
PileVehicles     每个时刻每个充电桩每个槽位的车辆明细
WaitingVehicles  每个时刻等候区车辆明细
Failures         回放失败事件及原因
```

## 7. 运行测试

运行全部后端测试：

```powershell
conda activate my_env
python -m pytest backend\tests -q
```

只运行 Excel 验收回放测试：

```powershell
conda activate my_env
python -m pytest backend\tests\test_excel_acceptance_replay.py -q
```

## 8. 注意事项

当前系统严格执行：

```text
等候区最大容量 N = 10
每个充电桩队列长度 M = 3
```

其中 `M=3` 表示：

```text
1 个正在充电位 + 2 个等待位
```

因此，当等候区已经有 10 辆车等待时，新的充电请求会被拒绝，并在 Excel 备注列中显示失败原因。

如果需要调整容量，可在管理端“参数设置”页修改：

```text
WaitingAreaSize
ChargingQueueLen
```

修改站点结构参数后，需要重置系统才能生效。

