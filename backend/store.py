"""
数据存储模块：管理 JSON 数据文件的读写，并同步到前端静态缓存文件。
"""
import json
import os
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 路径配置
BACKEND_DIR = Path(__file__).parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_ASSETS = PROJECT_DIR / "frontend" / "assets"
DATA_JSON_PATH = BACKEND_DIR / "data.json"
STATIC_DATA_JS_PATH = FRONTEND_ASSETS / "data.js"
META_JSON_PATH = FRONTEND_ASSETS / "data-meta.json"

# 线程锁，防止并发写入冲突
_write_lock = threading.Lock()


class NpEncoder(json.JSONEncoder):
    """处理 numpy 类型的 JSON 编码器"""
    def default(self, obj):
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def load_data():
    """从后端 data.json 加载数据"""
    if DATA_JSON_PATH.exists():
        try:
            with open(DATA_JSON_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载 data.json 失败: {e}")
    return None


def save_data(data):
    """保存数据到后端 data.json，并同步到前端 data.js 静态缓存"""
    with _write_lock:
        # 确保目录存在
        DATA_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        FRONTEND_ASSETS.mkdir(parents=True, exist_ok=True)

        # 保存后端 JSON
        with open(DATA_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, cls=NpEncoder)
        logger.info(f"数据已保存到 {DATA_JSON_PATH}")

        # 同步到前端 data.js（静态缓存，用于离线/降级渲染）
        with open(STATIC_DATA_JS_PATH, 'w', encoding='utf-8') as f:
            f.write("var basisData = ")
            json.dump(data, f, ensure_ascii=False, cls=NpEncoder)
            f.write(";\n")
        logger.info(f"静态缓存已同步到 {STATIC_DATA_JS_PATH}")

        # 保存元数据
        meta = data.get('meta', {})
        meta_info = {
            'last_updated': meta.get('last_updated', ''),
            'data_start': meta.get('data_start', ''),
            'data_end': meta.get('data_end', ''),
            'trading_days': meta.get('trading_days', 0),
        }
        with open(META_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(meta_info, f, ensure_ascii=False, indent=2)
        logger.info(f"元数据已保存到 {META_JSON_PATH}")


def get_status():
    """获取当前数据状态"""
    data = load_data()
    if data and 'meta' in data:
        meta = data['meta']
        return {
            'status': 'ok',
            'last_updated': meta.get('last_updated', '未知'),
            'data_start': meta.get('data_start', '未知'),
            'data_end': meta.get('data_end', '未知'),
            'trading_days': meta.get('trading_days', 0),
            'products': list(data.get('products', {}).keys()),
        }
    return {
        'status': 'no_data',
        'last_updated': '',
        'data_start': '',
        'data_end': '',
        'trading_days': 0,
        'products': [],
    }
