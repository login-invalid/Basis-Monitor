#!/bin/bash
cd /home/z/my-project/stock-index-futures-dashboard
export PYTHONPATH=/home/z/my-project/stock-index-futures-dashboard
exec python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 19080