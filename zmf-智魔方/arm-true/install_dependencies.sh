#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

python3 -m venv "$VENV_DIR"
chmod +x "$VENV_DIR/bin/python" "$VENV_DIR/bin/python3"

cat <<EOF
虚拟环境已创建：$VENV_DIR
当前项目仅依赖 Python 标准库，无需额外安装第三方包。
请使用以下命令运行：
  $VENV_DIR/bin/python $SCRIPT_DIR/arm_web_server.py
EOF
