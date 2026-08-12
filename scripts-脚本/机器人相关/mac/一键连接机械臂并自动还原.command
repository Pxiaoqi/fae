#!/bin/bash
# ============================================================
# 一键打通 Mac → 机器人 Orin → 机械臂网络
# 脚本运行期间可直连机械臂；退出（按回车/关窗口）自动还原 Orin 修改
#
# 用法（默认值如下，均可改）：
#   ./一键连接机械臂并自动还原.command [机器人IP] [机械臂网段] [机械臂IP]
#   默认: 192.168.90.1   192.168.1.0/24   192.168.1.19
# ============================================================

ROBOT_IP="${1:-192.168.90.1}"
ARM_NET="${2:-192.168.1.0/24}"
ARM_IP="${3:-192.168.1.19}"
SSH_USER="robot"
SSH_PASS="robot"

TMP_SH="/tmp/net-switch-$$.sh"
CHANGED=0

# ---------- 远程助手脚本（上传到 Orin 后 sudo 执行）----------
cat > "$TMP_SH" <<'REMOTE_EOF'
#!/bin/bash
# 用法: bash net-switch.sh apply|undo [ARM_NET] [ARM_IP]
ACTION="$1"
ARM_NET="${2:-192.168.1.0/24}"
ARM_IP="${3:-192.168.1.19}"

AP_IF=$(ip -4 -o addr show 2>/dev/null | awk -v ip=192.168.90.1 '$4 ~ ip {print $2; exit}')
ARM_IF=$(ip route get "$ARM_IP" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
AP_NET=$(ip route 2>/dev/null | awk -v d="$AP_IF" '$2==d && $1 ~ /\// {print $1; exit}')

[ -z "$AP_IF" ] && AP_IF="uap0"
[ -z "$AP_NET" ] && AP_NET="192.168.90.0/24"

if [ -z "$ARM_IF" ]; then
  echo "ERROR: 未找到机械臂网口（$ARM_IP 不可达）"
  exit 1
fi
echo "AP_IF=$AP_IF ARM_IF=$ARM_IF AP_NET=$AP_NET ARM_NET=$ARM_NET"

case "$ACTION" in
  apply)
    iptables -t nat -C POSTROUTING -o "$ARM_IF" -s "$AP_NET" -j MASQUERADE 2>/dev/null || \
      iptables -t nat -A POSTROUTING -o "$ARM_IF" -s "$AP_NET" -j MASQUERADE
    iptables -C FORWARD -i "$AP_IF" -o "$ARM_IF" -s "$AP_NET" -d "$ARM_NET" -j ACCEPT 2>/dev/null || \
      iptables -A FORWARD -i "$AP_IF" -o "$ARM_IF" -s "$AP_NET" -d "$ARM_NET" -j ACCEPT
    iptables -C FORWARD -i "$ARM_IF" -o "$AP_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
      iptables -A FORWARD -i "$ARM_IF" -o "$AP_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT
    echo "APPLIED"
    ;;
  undo)
    iptables -D FORWARD -i "$ARM_IF" -o "$AP_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
    iptables -D FORWARD -i "$AP_IF" -o "$ARM_IF" -s "$AP_NET" -d "$ARM_NET" -j ACCEPT 2>/dev/null
    iptables -t nat -D POSTROUTING -o "$ARM_IF" -s "$AP_NET" -j MASQUERADE 2>/dev/null
    echo "UNDONE"
    ;;
  *)
    echo "用法: net-switch.sh apply|undo [ARM_NET] [ARM_IP]"
    exit 1
    ;;
esac
exit 0
REMOTE_EOF

# ---------- 执行远程命令 ----------
do_ssh() {
  expect <<EOF
set timeout 60
spawn ssh -o StrictHostKeyChecking=accept-new ${SSH_USER}@${ROBOT_IP} {$1}
expect {
  -re "(?i)password:" { send "${SSH_PASS}\r"; exp_continue }
  -re "(?i)permission denied" { puts "AUTH_FAILED"; exit 1 }
  -re "(?i)no route to host|timed out|refused" { puts "UNREACHABLE"; exit 2 }
  eof
}
EOF
}

# ---------- 还原（退出时自动执行）----------
restore() {
  if [ "$CHANGED" = "1" ]; then
    echo ""
    echo "正在还原 Orin 网络配置..."
    do_ssh "echo robot | sudo -S bash ~/net-switch.sh undo ${ARM_NET} ${ARM_IP} 2>/dev/null; rm -f ~/net-switch.sh" >/dev/null 2>&1
    echo "已还原，Orin 恢复原状。"
  fi
  rm -f "$TMP_SH"
}
trap restore EXIT INT TERM HUP

# ---------- 上传并应用 ----------
echo "目标机器人: ${ROBOT_IP}   机械臂: ${ARM_NET} (${ARM_IP})"
echo "正在上传配置脚本..."
expect <<EOF
set timeout 60
spawn scp -o StrictHostKeyChecking=accept-new "$TMP_SH" ${SSH_USER}@${ROBOT_IP}:net-switch.sh
expect {
  -re "(?i)password:" { send "${SSH_PASS}\r"; exp_continue }
  -re "(?i)permission denied" { puts "AUTH_FAILED"; exit 1 }
  eof
}
EOF

echo "正在配置 Orin 转发..."
OUT=$(do_ssh "echo robot | sudo -S bash ~/net-switch.sh apply ${ARM_NET} ${ARM_IP} 2>&1")
echo "$OUT" | tail -4

if ! echo "$OUT" | grep -q "APPLIED"; then
  echo ""
  echo "[失败] 未能完成配置，请检查机器人/机械臂网络。"
  read -p "按回车键退出..."
  exit 1
fi

CHANGED=1

# ---------- 验证 ----------
if ping -c 2 -t 4 "$ARM_IP" >/dev/null 2>&1; then
  echo "机械臂 ${ARM_IP} 已可达 ✓"
else
  echo "警告：ping ${ARM_IP} 未通，请确认机械臂 IP 是否为本机所连网段"
fi

echo ""
echo "========================================"
echo " 配置完成，现在可以直接访问机械臂："
echo "   ${ARM_IP}（如示教器网页 http://${ARM_IP}/）"
echo "========================================"
echo ""
echo "使用期间请保持本窗口打开。"
echo "按回车键 或 关闭本窗口，将自动还原 Orin 配置。"
read -p "按回车键结束（还原）..."
