#!/usr/bin/env bash
# ============================================================
# 🍸 爱宝鸡尾酒 · 点单服务启动器（交互式向导）
# 运行: ./start.sh
# 高级用法（跳过向导）:
#   ./start.sh --direct   [--container 容器名] [--port 端口] [--yes]
#   ./start.sh --bridge   [--container 容器名] [--port 端口] [--yes]
#   ./start.sh --force    强制重新拷贝文件到容器（默认有文件则直接启动）
#   ./start.sh --check    只检查端口状态，不启动
#   ./start.sh --wizard   强制重新走一遍配置向导
#
# 首次配置后会保存 .startup.conf 并生成 quickstart.sh：
#   宿主机：./quickstart.sh 一键启动（免交互）
#   容器内：cd /opt/coffee-order-ui && ./quickstart.sh 一键启动
# ============================================================
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
CONF="$SRC/.startup.conf"
MODE=""
CONTAINER=""
PORT=""
AUTO=0
FORCE_COPY=0
CHECK_ONLY=0
WIZARD=0

while [ $# -gt 0 ]; do
  case "$1" in
    --container) CONTAINER="$2"; shift 2 ;;
    --port)      PORT="$2"; shift 2 ;;
    --direct)    MODE="direct"; shift ;;
    --bridge)    MODE="bridge"; shift ;;
    --yes)       AUTO=1; shift ;;
    --force)     FORCE_COPY=1; shift ;;
    --check)     CHECK_ONLY=1; shift ;;
    --wizard)    WIZARD=1; shift ;;
    -h|--help)
      sed -n '1,10p' "$0"; exit 0 ;;
    *) echo "未知参数: $1（-h 查看帮助）" >&2; exit 1 ;;
  esac
done

# 使用已保存配置（免交互）；--wizard 可强制重新配置
if [ "$WIZARD" != "1" ] && [ -z "$MODE" ] && [ -z "$CONTAINER" ] && [ -z "$PORT" ] && [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF"
  AUTO=1
  echo ">> 使用上次配置：$MODE / $CONTAINER / $PORT（重新配置请加 --wizard）"
fi

# 运行中的容器列表
running=()
if command -v docker >/dev/null 2>&1; then
  while IFS= read -r line; do
    [ -n "$line" ] && running+=("$line")
  done < <(docker ps --format '{{.Names}}' 2>/dev/null || true)
fi

echo ""
echo "=============================================="
echo "  🤖 智魔方点单系统启动器"
echo "=============================================="

# ---------- 1. 选择运行方式 ----------
if [ -z "$MODE" ]; then
  echo ""
  echo "请选择运行方式："
  echo "  1) 导入容器内运行（直写模式）"
  echo "     · 程序自动拷进容器并启动"
  echo "     · 订单列表/状态每秒刷新，实时性最好（推荐）"
  echo "  2) 宿主机桥接运行"
  echo "     · 不进入容器，通过 docker 下单"
  echo "     · 订单状态 3 秒刷新"
  printf "输入 1 或 2 [默认 1]: "
  read -r CHOICE
  case "$CHOICE" in
    2|b|B|bridge) MODE="bridge" ;;
    *) MODE="direct" ;;
  esac
fi

# ---------- 2. 选择容器 ----------
if [ -z "$CONTAINER" ]; then
  echo ""
  if [ "${#running[@]}" -eq 0 ]; then
    echo "提示：没有检测到运行中的容器。"
    printf "请输入容器名 [默认 coffee-v2.2.5]: "
    read -r C
    CONTAINER="${C:-coffee-v2.2.5}"
  elif [ "${#running[@]}" -eq 1 ]; then
    CONTAINER="${running[0]}"
    echo "检测到运行中的容器：${running[0]}（唯一，自动选用）"
  else
    echo "检测到以下运行中的容器："
    for i in "${!running[@]}"; do
      echo "  $((i + 1))) ${running[$i]}"
    done
    printf "输入序号或直接输入容器名 [默认 ${running[0]}]: "
    read -r C
    if [ -z "$C" ]; then
      CONTAINER="${running[0]}"
    elif [[ "$C" =~ ^[0-9]+$ ]] && [ "$C" -ge 1 ] && [ "$C" -le "${#running[@]}" ]; then
      CONTAINER="${running[$((C - 1))]}"
    else
      CONTAINER="$C"
    fi
  fi
fi

# ---------- 3. 选择端口 ----------
if [ -z "$PORT" ]; then
  printf "请输入点单服务端口 [默认 8077]: "
  read -r P
  PORT="${P:-8077}"
fi
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "端口无效: $PORT" >&2
  exit 1
fi

# ---------- 端口检查 ----------
host_port_open() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":$1 "
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | grep -q ":$1 "
  else
    return 1
  fi
}

container_port_open() {
  docker exec "$CONTAINER" sh -c \
    "(command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':$PORT ') || \
     (command -v netstat >/dev/null 2>&1 && netstat -ltn 2>/dev/null | grep -q ':$PORT ')" \
    2>/dev/null
}

echo ""
echo "---------- 端口 $PORT 状态检查 ----------"
if host_port_open "$PORT"; then
  HOST_PORT_STATE="开启"
else
  HOST_PORT_STATE="关闭"
fi
echo "  宿主机 $PORT : $HOST_PORT_STATE"
if [ "$MODE" = "direct" ]; then
  if container_port_open; then
    CONTAINER_PORT_STATE="开启（服务可能在运行）"
  else
    CONTAINER_PORT_STATE="关闭"
  fi
  echo "  容器内 $PORT : $CONTAINER_PORT_STATE"
fi
echo "------------------------------------------"

if [ "$CHECK_ONLY" = "1" ]; then
  echo "（--check：仅检查，不启动）"
  exit 0
fi

if host_port_open "$PORT" && [ "$AUTO" = "0" ]; then
  printf "宿主机 $PORT 已开启（可能是转发容器或其它服务），是否继续？[Y/n]: "
  read -r GO
  case "$GO" in
    n|N|no) echo "已取消"; exit 0 ;;
  esac
fi

# ---------- 4. 汇总确认 ----------
echo ""
echo "=============================================="
if [ "$MODE" = "direct" ]; then
  echo "  运行方式：导入容器内运行（直写模式，1 秒刷新）"
else
  echo "  运行方式：宿主机桥接（3 秒刷新）"
fi
echo "  目标容器：$CONTAINER"
echo "  服务端口：$PORT"
echo "=============================================="
if [ "$AUTO" = "0" ]; then
  printf "确认启动？回车继续，输入 n 取消: "
  read -r OK
  case "$OK" in
    n|N|no) echo "已取消"; exit 0 ;;
  esac
fi

# ---------- 保存配置并生成一键启动脚本 ----------
printf 'MODE=%s\nCONTAINER=%s\nPORT=%s\n' "$MODE" "$CONTAINER" "$PORT" > "$CONF"
chmod 600 "$CONF"
cat > "$SRC/quickstart.sh" <<'QUICK'
#!/usr/bin/env bash
# 智魔方点单系统 · 一键启动（免交互，由 start.sh 自动生成）
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$SRC/.startup.conf" ]; then
  echo "未找到 .startup.conf，请先运行 ./start.sh 完成首次配置" >&2
  exit 1
fi
# shellcheck disable=SC1090
. "$SRC/.startup.conf"
exec "$SRC/start.sh" --"$MODE" --container "$CONTAINER" --port "$PORT" --yes "$@"
QUICK
chmod +x "$SRC/quickstart.sh"
echo ">> 已生成一键启动脚本：$SRC/quickstart.sh"

# ---------- 执行 ----------
if [ "$MODE" = "direct" ]; then
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "错误：容器 $CONTAINER 未在运行" >&2
    exit 1
  fi
  DEST="/opt/coffee-order-ui"
  REQUIRED="server.py index.html style.css app.js menu_config.yaml timing_config.yaml"
  echo ""
  # 检查容器内是否已有程序文件：有则直接启动，缺才询问是否拷贝
  need_copy=0
  missing=""
  for f in $REQUIRED; do
    if ! docker exec "$CONTAINER" sh -c "test -f '$DEST/$f'" 2>/dev/null; then
      need_copy=1
      missing="$missing $f"
    fi
  done

  if [ "$FORCE_COPY" = "1" ]; then
    need_copy=1
    echo ">> --force：重新拷贝全部文件到 $CONTAINER:$DEST"
  elif [ "$need_copy" = "0" ]; then
    echo ">> 容器内已存在程序文件，直接启动（跳过拷贝）"
  else
    echo ">> 容器内缺少文件:$missing"
    if [ "$AUTO" = "1" ]; then
      need_copy=1
      echo "   （--yes：自动拷贝）"
    else
      printf "是否拷贝到容器？[Y/n]（n=尝试直接启动）: "
      read -r CP
      case "$CP" in
        n|N|no)
          need_copy=0
          echo "   （跳过拷贝；若文件缺失启动可能失败）"
          ;;
        *) need_copy=1 ;;
      esac
    fi
  fi

  if [ "$need_copy" = "1" ]; then
    docker exec "$CONTAINER" mkdir -p "$DEST"
    for f in $REQUIRED; do
      if [ -f "$SRC/$f" ]; then
        docker cp "$SRC/$f" "$CONTAINER:$DEST/$f"
        echo "   ✓ $f"
      fi
    done
    if [ -f "$SRC/menu_overrides.json" ]; then
      docker cp "$SRC/menu_overrides.json" "$CONTAINER:$DEST/menu_overrides.json"
      echo "   ✓ menu_overrides.json"
    fi
    if [ -f "$SRC/.startup.conf" ]; then
      docker cp "$SRC/.startup.conf" "$CONTAINER:$DEST/.startup.conf"
      echo "   ✓ .startup.conf"
    fi
    if [ -f "$SRC/container-start.sh" ]; then
      docker cp "$SRC/container-start.sh" "$CONTAINER:$DEST/quickstart.sh"
      docker exec "$CONTAINER" chmod +x "$DEST/quickstart.sh"
      echo "   ✓ 容器内一键启动脚本 quickstart.sh"
    fi
  fi

  echo ">> 停止旧实例（如有）"
  docker exec "$CONTAINER" pkill -f "server[.]py" 2>/dev/null || true
  sleep 1  # 等旧进程释放端口
  echo ">> 容器内启动中 ..."
  docker exec -d -e COFFEE_DIRECT=1 -e COFFEE_UI_PORT="$PORT" \
    "$CONTAINER" python3 "$DEST/server.py"
  sleep 2

  # 端口可达性：容器 host 网络或已发布端口无需转发；
  # Docker Desktop 等 bridge 网络下，宿主机直连不到容器 IP，需要转发旁路容器
  HOST_OK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 \
    "http://127.0.0.1:$PORT/api/health" 2>/dev/null || echo 000)
  NET_MODE=$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CONTAINER" 2>/dev/null || echo bridge)
  if [ "$HOST_OK" != "200" ] && [ "$NET_MODE" != "host" ]; then
    CIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER")
    FWD="coffee-ui-fwd-$PORT"
    echo ">> 宿主机直连不到容器端口，创建端口转发旁路容器 $FWD ..."
    docker rm -f "$FWD" 2>/dev/null || true
    if docker images -q alpine >/dev/null 2>&1; then
      docker run -d --name "$FWD" --restart unless-stopped \
        -p "$PORT:$PORT" alpine sh -c "nc -lk -p $PORT -e nc $CIP $PORT" \
        && echo "   ✓ 端口已发布（$PORT -> 容器 $CIP:$PORT）"
      sleep 2
    else
      echo "   ⚠ 未找到 alpine 镜像，无法自动发布端口（机器人 host 网络则无需）"
    fi
  fi

  echo ""
  echo "✅ 完成！其他设备访问："
  echo "   本机: http://127.0.0.1:$PORT"
  docker exec "$CONTAINER" hostname -I 2>/dev/null | awk '{print "   http://"$1":'"$PORT"'"}' || true
  echo "   （host 网络用机器人本机 IP；bridge 网络需 -p $PORT:$PORT 发布端口）"
else
  if ! command -v docker >/dev/null 2>&1; then
    echo "错误：未找到 docker 命令" >&2
    exit 1
  fi
  echo ""
  echo ">> 宿主机桥接模式启动中 ..."
  pkill -f "$SRC/server.py" 2>/dev/null || true
  cd "$SRC"
  COFFEE_CONTAINER="$CONTAINER" COFFEE_UI_PORT="$PORT" \
    nohup python3 server.py > server.log 2>&1 &
  sleep 1
  echo ""
  echo "✅ 已启动！日志：$SRC/server.log"
  echo "   停止：pkill -f $SRC/server.py"
fi
