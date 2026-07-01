"""持久运行 uvicorn 服务器的启动脚本"""
import sys
import os

os.chdir('/home/z/my-project/stock-index-futures-dashboard')
sys.path.insert(0, '/home/z/my-project/stock-index-futures-dashboard')
os.environ['PYTHONPATH'] = '/home/z/my-project/stock-index-futures-dashboard'

import uvicorn
from backend.main import app

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=19080, log_level='info')