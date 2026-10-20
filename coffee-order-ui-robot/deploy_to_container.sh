#!/usr/bin/env bash
# 部署点单服务到机器人容器内（容器内直写模式，推荐）
#
# 用法:
#   ./deploy_to_container.sh [容器名] [容器内安装路径]
#   例: ./deploy_to_container.sh coffee-v2.2.5 /opt/coffee-order-ui
#
# 前提:
#   1) 宿主机能执行 docker 命令
#   2) 容器内有 python3
#   3) 容器内存在 /root/AlphaBrainSystem/tools/interfaces/coffee_order_manager_12.py

set -euo pipefail

CONTAINER="${1:-coffee-v2.2.5}"
DEST="${2:-/opt/coffee-order-ui}"
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT="${COFFEE_UI_PORT:-8077}"

echo ">> 容器: $CONTAINER"
echo ">> 安装目录: $DEST"

docker exec "$CONTAINER" mkdir -p "$DEST"
for f in server.py index.html style.css app.js menu_config.yaml timing_config.yaml; do
  docker cp "$SRC/$f" "$CONTAINER:$DEST/$f"
  echo "   copied $f"
done

if [ -f "$SRC/menu_overrides.json" ]; then
  docker cp "$SRC/menu_overrides.json" "$CONTAINER:$DEST/menu_overrides.json"
  echo "   copied menu_overrides.json"
fi

if [ -f "$SRC/.startup.conf" ]; then
  docker cp "$SRC/.startup.conf" "$CONTAINER:$DEST/.startup.conf"
  echo "   copied .startup.conf"
fi

if [ -f "$SRC/container-start.sh" ]; then
  docker cp "$SRC/container-start.sh" "$CONTAINER:$DEST/quickstart.sh"
  docker exec "$CONTAINER" chmod +x "$DEST/quickstart.sh"
  echo "   copied quickstart.sh (容器内一键启动)"
fi

echo ">> 停止旧实例（如有）"
docker exec "$CONTAINER" pkill -f "$DEST/server.py" 2>/dev/null || true
sleep 1

echo ">> 启动点单服务 (COFFEE_DIRECT=1, port $PORT)"
docker exec -d -e COFFEE_DIRECT=1 -e COFFEE_UI_PORT="$PORT" \
  "$CONTAINER" python3 "$DEST/server.py"

sleep 2
echo ">> 容器内健康检查:"
docker exec "$CONTAINER" sh -c \
  "curl -s http://127.0.0.1:$PORT/api/health || echo '(容器内无 curl 也可从外部访问)'"
echo
echo "完成。电脑连上机器人热点后访问:"
docker exec "$CONTAINER" hostname -I 2>/dev/null | awk '{print "   http://"$1":'"$PORT"'"}' || true
echo "   （如容器为 host 网络，请用机器人本机 IP 加端口 $PORT）"
