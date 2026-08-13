#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN=""
for candidate in "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/.venv-1/bin/python" "$(command -v python3 || true)" "$(command -v python || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    if "$candidate" -c 'import alphabot' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
 done

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi

if [[ $# -eq 0 ]]; then
  set -- --docker "coffee-v2.1.7"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "未找到可用的 Python 解释器。" >&2
  read -r -n 1 -s -p "按任意键退出..."
  echo
  # 不执行 exit：被 source 时返回调用方，直接执行时正常结束，终端保持打开
  if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    return 1
  fi
fi

# 不再使用 exec：服务退出后停留在终端，避免终端直接关闭
if "$PYTHON_BIN" "$SCRIPT_DIR/arm_web_server.py" "$@"; then
  status=0
else
  status=$?
fi

echo
echo "Web 服务已停止（退出码 $status）。"
read -r -n 1 -s -p "按任意键退出..."
echo
# 不执行 exit：脚本结束后返回终端提示符，终端保持打开
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  return "$status"
fi
