"""智能充电桩调度计费系统 —— FastAPI 入口。

启动：cd backend && uvicorn app.main:app --reload --port 8000
架构：Controller(api/) → Service(services/) → Domain(domain/) → Repository(db.py)
模拟引擎（充电桩设备）：后台任务每 0.25s 调用 AppContext.step()。
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.admin import admin_router
from .api.controllers import (bill_router, charging_router, pile_event_router,
                              pile_router, user_router)
from .context import get_context, init_context
from .domain.enums import BusinessError

logger = logging.getLogger("charging")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
DATA_DIR = os.path.join(BASE_DIR, "data")


async def _engine_loop():
    """模拟充电桩设备：自动上报开始充电/充电完成，并兜底自动叫号。"""
    while True:
        try:
            get_context().step()
        except Exception:  # 引擎永不中断
            logger.exception("engine step failed")
        await asyncio.sleep(0.25)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_context(DATA_DIR)
    task = asyncio.create_task(_engine_loop())
    yield
    task.cancel()


app = FastAPI(title="智能充电桩调度计费系统", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BusinessError)
async def business_error_handler(_: Request, exc: BusinessError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    """输入类错误（参数越界、时刻/日期格式错误等）以可读的 400 返回，
    而非 500——验收时误填参数/时间不会表现为"系统崩溃"。"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


for router in (user_router, charging_router, pile_event_router,
               pile_router, bill_router, admin_router):
    app.include_router(router, prefix="/api")


# 若前端已构建（frontend/dist），则由后端直接托管，单端口即可演示。
# SPA 回退：/api 之外的未知路径一律返回 index.html（支持 /admin/monitor 等深链接刷新）
_dist = os.path.join(os.path.dirname(BASE_DIR), "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    _dist_real = os.path.realpath(_dist)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # 仅在规范化后仍位于 dist 目录内才直接返回静态文件，防止 ../ 路径穿越读取仓库任意文件
        candidate = os.path.realpath(os.path.join(_dist, full_path))
        if (full_path and (candidate == _dist_real
                           or candidate.startswith(_dist_real + os.sep))
                and os.path.isfile(candidate)):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_dist, "index.html"))
