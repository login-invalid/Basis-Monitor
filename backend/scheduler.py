"""
定时任务模块：每个交易日收盘后自动更新数据。
"""
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = None
_update_lock = threading.Lock()
_last_update_result = None


def _do_update():
    """执行定时更新"""
    global _last_update_result
    from . import store
    from . import fetcher

    if _update_lock.locked():
        logger.info("更新任务已在运行中，跳过")
        return

    with _update_lock:
        logger.info("=== 定时更新开始 ===")
        try:
            existing = store.load_data()
            data = fetcher.incremental_fetch(existing)
            store.save_data(data)
            _last_update_result = {'success': True, 'message': '定时更新成功'}
            logger.info("=== 定时更新成功 ===")
        except Exception as e:
            _last_update_result = {'success': False, 'message': f'定时更新失败: {e}'}
            logger.error(f"=== 定时更新失败: {e} ===")


def start_scheduler():
    """启动定时任务"""
    global _scheduler
    if _scheduler is not None:
        logger.warning("定时任务已启动，跳过")
        return

    _scheduler = BackgroundScheduler(timezone='Asia/Shanghai')

    # 每个交易日 16:00 (北京时间) 执行
    # 周一到周五
    _scheduler.add_job(
        _do_update,
        CronTrigger(day_of_week='mon-fri', hour=16, minute=0, timezone='Asia/Shanghai'),
        id='daily_update',
        name='每日收盘后更新股指期货基差数据',
        misfire_grace_time=3600,
    )

    _scheduler.start()
    logger.info("定时任务已启动: 每交易日 16:00 (北京时间) 自动更新")


def stop_scheduler():
    """停止定时任务"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("定时任务已停止")


def get_last_update_result():
    """获取最近一次更新结果"""
    return _last_update_result
