"""
FastAPI 主应用：提供数据查询、手动更新、健康检查 API。
"""
import logging
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from . import store
from . import fetcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Stock Index Basis Tracker API", version="1.0.0")

# CORS 配置（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端静态文件目录
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# 更新锁
_update_lock = threading.Lock()
_last_manual_result = None


@app.get("/api/status")
async def get_status():
    """健康检查 + 数据状态"""
    status = store.get_status()
    return JSONResponse(status)


@app.get("/api/data")
async def get_data():
    """返回最新完整 JSON 数据"""
    data = store.load_data()
    if data:
        return JSONResponse(data)
    return JSONResponse({'error': '数据尚未初始化'}, status_code=503)


@app.post("/api/update")
async def manual_update():
    """手动触发增量更新"""
    global _last_manual_result

    if _update_lock.locked():
        return JSONResponse({'status': 'running', 'message': '更新任务正在运行中'}, status_code=409)

    with _update_lock:
        logger.info("=== 手动更新开始 ===")
        try:
            existing = store.load_data()
            data = fetcher.incremental_fetch(existing)
            store.save_data(data)
            status = store.get_status()
            _last_manual_result = {'status': 'success', 'message': '更新成功', 'data_status': status}
            logger.info("=== 手动更新成功 ===")
            return JSONResponse(_last_manual_result)
        except Exception as e:
            _last_manual_result = {'status': 'error', 'message': f'更新失败: {str(e)}'}
            logger.error(f"=== 手动更新失败: {e} ===")
            return JSONResponse(_last_manual_result, status_code=500)


@app.post("/api/full-update")
async def full_update():
    """全量重新拉取数据（慎用，耗时较长）"""
    global _last_manual_result

    if _update_lock.locked():
        return JSONResponse({'status': 'running', 'message': '更新任务正在运行中'}, status_code=409)

    with _update_lock:
        logger.info("=== 全量更新开始 ===")
        try:
            data = fetcher.full_fetch()
            store.save_data(data)
            status = store.get_status()
            _last_manual_result = {'status': 'success', 'message': '全量更新成功', 'data_status': status}
            logger.info("=== 全量更新成功 ===")
            return JSONResponse(_last_manual_result)
        except Exception as e:
            _last_manual_result = {'status': 'error', 'message': f'全量更新失败: {str(e)}'}
            logger.error(f"=== 全量更新失败: {e} ===")
            return JSONResponse(_last_manual_result, status_code=500)


# ============================================================
# 静态前端服务（开发模式用；生产环境用 Nginx）
# ============================================================
@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
app.mount("/_shared", StaticFiles(directory=FRONTEND_DIR / "_shared"), name="_shared")


@app.on_event("startup")
async def startup_event():
    """启动时初始化定时任务"""
    try:
        from . import scheduler
        scheduler.start_scheduler()
        logger.info("应用启动完成，定时任务已就绪")
    except Exception as e:
        logger.warning(f"定时任务启动失败（不影响API使用）: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时停止定时任务"""
    try:
        from . import scheduler
        scheduler.stop_scheduler()
    except Exception:
        pass
