#!/bin/bash
# ============================================================
# 一键更新调参脚本（在机器人上运行）
# 1. 自动进入本仓库目录
# 2. git pull 拉取最新代码
# 3. 显示结果，保持终端打开
#
# 用法：bash update.sh（或直接运行 ./update.sh）
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || {
  echo "无法进入目录 $SCRIPT_DIR"
  read -p "按回车键退出..."
  exit 1
}

if [ ! -d "$SCRIPT_DIR/.git" ]; then
  echo "错误：当前目录不是 git 仓库，请确认 update.sh 位于 /home/data/robot/arm-true 下"
  read -p "按回车键退出..."
  exit 1
fi

echo "===== 正在拉取最新调参脚本（$(date '+%Y-%m-%d %H:%M:%S')）====="
git pull

STATUS=$?
echo ""
if [ "$STATUS" -eq 0 ]; then
  echo "========================================"
  echo " 更新完成"
  echo " 当前版本: $(git log -1 --oneline 2>/dev/null)"
  echo "========================================"
else
  echo "[失败] 更新未完成，请检查网络或本地冲突（运行 git status 查看）"
  echo "提示：若有本地修改导致冲突，可先执行 git stash 再重新运行本脚本"
fi
echo ""
read -p "按回车键退出..."
