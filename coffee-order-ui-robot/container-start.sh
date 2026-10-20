#!/usr/bin/env bash
# 智魔方点单系统 · 容器内一键启动
# 部署时由 start.sh / deploy_to_container.sh 复制到容器 /opt/coffee-order-ui/quickstart.sh
set -euo pipefail

cd "$(dirname "$0")"

PORT="${COFFEE_UI_PORT:-8077}"
if [ -f .startup.conf ]; then
  # shellcheck disable=SC1091
  . ./.startup.conf
  PORT="${PORT:-8077}"
fi

echo ">> 停止旧实例（如有）"
pkill -f "server[.]py" 2>/dev/null || true
sleep 1

echo ">> 启动点单服务（COFFEE_DIRECT=1, 端口 $PORT）"
COFFEE_DIRECT=1 COFFEE_UI_PORT="$PORT" nohup python3 -u server.py > server.log 2>&1 &
sleep 2

echo "✅ 点单服务已启动（容器内端口 $PORT）"
curl -s --max-time 10 "http://127.0.0.1:$PORT/api/health" || true
echo
