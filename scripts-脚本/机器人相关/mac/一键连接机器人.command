#!/bin/bash
# ============================================================
# 一键切换 RustDesk 连接目标机器人
# 1. SSH 到机器人，自动获取 rustdesk ID 和 hbbs Key
# 2. 自动更新本机 RustDesk 配置（服务器 + Key）
# 3. 重启 RustDesk，ID 复制到剪贴板，可直接连接
# ============================================================

SSH_USER="robot"
SSH_PASS="robot"

ROBOT_IP="${1:-192.168.90.1}"

CFG_DIR="$HOME/Library/Preferences/com.carriez.RustDesk"
CFG_FILE="$CFG_DIR/RustDesk2.toml"

echo "正在连接 ${SSH_USER}@${ROBOT_IP} 获取 RustDesk 信息..."

OUTPUT=$(expect <<EOS
set timeout 45
spawn ssh -o StrictHostKeyChecking=accept-new ${SSH_USER}@${ROBOT_IP} {echo "===RUSTDESK_ID==="; rustdesk --get-id 2>/dev/null; echo "===RUSTDESK_KEY==="; docker logs hbbs 2>/dev/null | grep Key | tail -1}
expect {
  -re "(?i)password:" { send "${SSH_PASS}\r"; exp_continue }
  -re "(?i)permission denied" { puts "AUTH_FAILED"; exit 1 }
  -re "(?i)no route to host|timed out|refused" { puts "UNREACHABLE"; exit 2 }
  eof
}
EOS
)

ID=$(printf '%s\n' "$OUTPUT" | sed -n '/===RUSTDESK_ID===/,/===RUSTDESK_KEY===/p' | tr -d '\r' | grep -E '^[0-9]+$' | head -1)
KEY=$(printf '%s\n' "$OUTPUT" | sed -n '/===RUSTDESK_KEY===/,$p' | tr -d '\r' | grep 'Key:' | tail -1 | sed 's/.*Key: *//')

if [ -z "$ID" ] || [ -z "$KEY" ]; then
  echo ""
  echo "[失败] 未获取到完整信息（ID='$ID' Key='$KEY'）"
  echo "请确认：1) 机器人能 SSH 登录  2) 机器人已安装 rustdesk  3) hbbs 容器在运行"
  read -p "按回车键退出..."
  exit 1
fi

# 备份当前配置
cp "$CFG_FILE" "$CFG_FILE.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null

# 退出 RustDesk（避免退出时覆盖配置）
osascript -e 'tell application "RustDesk" to quit' >/dev/null 2>&1
sleep 2
if pgrep -i rustdesk >/dev/null 2>&1; then
  pkill -i rustdesk 2>/dev/null
  sleep 1
fi

# 更新配置：服务器地址 + Key
sed -i '' "s|^rendezvous_server = .*|rendezvous_server = '${ROBOT_IP}:21116'|" "$CFG_FILE"
sed -i '' "s|^custom-rendezvous-server = .*|custom-rendezvous-server = '${ROBOT_IP}'|" "$CFG_FILE"
sed -i '' "s|^key = .*|key = '${KEY}'|" "$CFG_FILE"

# 重启 RustDesk，ID 复制到剪贴板
open -a RustDesk
printf '%s' "$ID" | pbcopy

echo ""
echo "========================================"
echo " 目标机器人 : ${ROBOT_IP}"
echo " RustDesk ID : ${ID}   (已复制到剪贴板)"
echo " RustDesk Key: ${KEY}"
echo "========================================"
echo "下一步："
echo "1. 打开 RustDesk，在\"远程设备 ID\"粘贴 $ID"
echo "2. 点击\"连接\""
echo "3. 输入该机器人的 RustDesk 访问密码（若已信任设备则直接连）"
echo "4. 首次连新机器人若提示确认服务器密钥，点\"信任/确认\"即可"
echo ""
read -p "按回车键退出..."
