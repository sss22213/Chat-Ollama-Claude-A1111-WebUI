#!/usr/bin/env bash
# 一鍵啟動後端 (8000) + 前端 (5273)。Ctrl+C 同時關閉。
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 後端
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 &
BACK=$!

# 前端
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev &
FRONT=$!

trap "kill $BACK $FRONT 2>/dev/null" EXIT INT TERM
echo ""
echo "  後端  → http://127.0.0.1:8000"
echo "  前端  → http://127.0.0.1:5273"
echo ""
wait
