# Stock Index Basis Tracker Dashboard

IF / IH / IC / IM 四大股指期货品种的当月、下月、当季、隔季合约升贴水追踪系统，支持近3年历史基差走势对比，提供定时自动更新与手动触发更新。

## 快速部署

### 方式一：Docker Compose（推荐）

```bash
# 一键启动（前端 + 后端 + Nginx）
docker compose up -d

# 访问
# 看板: http://your-server/
# API:  http://your-server/api/status
```

### 方式二：本地开发

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动后端（含静态前端服务）
cd ..
PYTHONPATH=backend uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 访问 http://localhost:8000/
```

## 项目结构

```
stock-index-futures-dashboard/
├── frontend/              # 纯静态前端
│   ├── index.html        # 主页面
│   ├── assets/
│   │   ├── charts.js     # 图表逻辑（动态加载+回退）
│   │   ├── data.js       # 静态缓存数据（后端同步生成）
│   │   └── data-meta.json
│   └── _shared/
│       ├── js/echarts.min.js
│       └── fonts/
├── backend/               # FastAPI 后端
│   ├── main.py           # API 路由
│   ├── fetcher.py        # 数据采集与基差计算
│   ├── store.py          # 数据存储与静态文件同步
│   ├── scheduler.py      # 定时任务
│   ├── data.json         # 后端数据缓存
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml    # 一键部署
├── nginx.conf            # Nginx 反代配置
└── README.md
```

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 健康检查 + 数据状态 |
| `/api/data` | GET | 返回最新完整 JSON 数据 |
| `/api/update` | POST | 手动触发增量更新 |
| `/api/full-update` | POST | 全量重新拉取（慎用） |

## 数据更新机制

- **定时自动更新**：每个交易日 16:00（北京时间）自动执行增量更新
- **手动触发更新**：页面右上角"更新数据"按钮，随时触发
- **静态缓存保底**：后端每次更新同步写入 `frontend/assets/data.js`，即使后端宕机页面也不会白屏

## 技术栈

- 前端：HTML + ECharts（纯静态，无框架依赖）
- 后端：Python + FastAPI + APScheduler
- 数据源：akshare（新浪财经）
- 部署：Docker + Nginx
