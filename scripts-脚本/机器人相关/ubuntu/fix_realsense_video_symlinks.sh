#!/usr/bin/env bash
# ============================================================
# 固定 RealSense 摄像头 /dev/video* 节点
# ------------------------------------------------------------
# 原理：/dev/videoN 由内核按枚举顺序分配，重启/插拔后会变，
#       无法直接固定编号。本脚本通过 udev 规则按 USB 序列号
#       为每个 video 节点生成稳定软链：
#           /dev/realsense/<型号>-<序列号>-video<序号>
#       重启、重新插拔、换 USB 口后软链依然不变。
#
# 用法：
#   sudo bash fix_realsense_video_symlinks.sh          # 安装
#   sudo bash fix_realsense_video_symlinks.sh --uninstall
#
# 注意：这里用的序列号是 USB sysfs 里的 serial（即 librealsense
#       里 rs-enumerate-devices 打印的 "Firmware Update Id"），
#       每台相机唯一且稳定。
# ============================================================
set -euo pipefail

HELPER="/usr/local/bin/realsense-v4l-name.sh"
RULES="/etc/udev/rules.d/99-realsense-fixed.rules"

# 以 root 运行（非 root 时自动用 sudo 重跑）
if [ "$(id -u)" -ne 0 ]; then
  echo "[!] 需要 root 权限，正在用 sudo 重新执行..."
  exec sudo bash "$0" "$@"
fi

if [ "${1:-}" = "--uninstall" ]; then
  echo "[*] 卸载中..."
  rm -f "$HELPER" "$RULES"
  rm -f /dev/realsense/*
  rmdir /dev/realsense 2>/dev/null || true
  udevadm control --reload-rules
  udevadm trigger --subsystem-match=video4linux
  echo "[✓] 已卸载，/dev/videoN 恢复默认行为"
  exit 0
fi

echo "[*] 写入 udev 辅助程序: $HELPER"
cat > "$HELPER" <<'EOF'
#!/usr/bin/env bash
# udev IMPORT 程序：为 RealSense 的每个 video 节点输出稳定名称
# 输出: RS_V4L_NAME=<型号>-<序列号>-video<序号>
KERNEL_NAME="$1"
[ -n "$KERNEL_NAME" ] || exit 1

DEV_PATH=$(readlink -f "/sys/class/video4linux/$KERNEL_NAME/device" 2>/dev/null) || exit 1
# 去掉最后一个 "接口目录"（形如 2-2:1.0），得到相机 USB 设备目录，如 .../usb2/2-2
USB_DEV_PATH=$(printf '%s\n' "$DEV_PATH" | sed 's#/[^/]*:[0-9][0-9.]*$##')
printf '%s' "$USB_DEV_PATH" | grep -q '/usb[0-9]/' || exit 1

SERIAL=$(cat "$USB_DEV_PATH/serial" 2>/dev/null) || SERIAL="unknown"
PRODUCT=$(cat "$USB_DEV_PATH/product" 2>/dev/null) || PRODUCT=""
PID=$(cat "$USB_DEV_PATH/idProduct" 2>/dev/null) || PID=""

case "$PRODUCT:$PID" in
  *405*) MODEL="D405" ;;
  *435*) MODEL="D435" ;;
  *) exit 1 ;;
esac

# 统计同一台相机下的 video 节点，确定本节点序号（顺序稳定：深度/红外/RGB 按固定次序注册）
IDX=0
for v in $(ls -d /sys/class/video4linux/video* 2>/dev/null || true | sort -V); do
  d=$(readlink -f "$v/device" 2>/dev/null) || continue
  case "$d" in
    "$USB_DEV_PATH"/*)
      if [ "$v" = "/sys/class/video4linux/$KERNEL_NAME" ]; then
        echo "RS_V4L_NAME=${MODEL}-${SERIAL}-video${IDX}"
        exit 0
      fi
      IDX=$((IDX+1))
      ;;
  esac
done
exit 1
EOF
chmod +x "$HELPER"

echo "[*] 写入 udev 规则: $RULES"
cat > "$RULES" <<'EOF'
# 固定 Intel RealSense 的 /dev/video* 节点 -> /dev/realsense/<型号>-<序列号>-video<序号>
SUBSYSTEM=="video4linux", KERNEL=="video*", SUBSYSTEMS=="usb", ATTRS{idVendor}=="8086", ATTRS{idProduct}=="0b07|0b5b", IMPORT{program}="/usr/local/bin/realsense-v4l-name.sh %k"
ENV{RS_V4L_NAME}=="?*", SYMLINK+="realsense/$env{RS_V4L_NAME}", MODE:="0666", GROUP:="plugdev"
EOF

echo "[*] 重新加载 udev 规则并触发..."
mkdir -p /dev/realsense
udevadm control --reload-rules
udevadm trigger --subsystem-match=video4linux
sleep 2

echo ""
echo "======================================================"
echo " /dev/realsense/ 下已生成的稳定软链："
echo "======================================================"
ls -l /dev/realsense/ 2>/dev/null || true

echo ""
echo " 相机 -> 软链 对照（序列号为 sysfs serial / FW Update Id）："
for dev in /sys/bus/usb/devices/*; do
  pid=$(cat "$dev/idProduct" 2>/dev/null || true)
  case "$pid" in
    0b07|0b5b)
      serial=$(cat "$dev/serial" 2>/dev/null || echo unknown)
      product=$(cat "$dev/product" 2>/dev/null || echo "")
      model=$(printf '%s' "$product" | grep -oE 'D4[0-9]{2}' | head -1)
      links=$(ls -d "/dev/realsense/${model}-${serial}-video"* 2>/dev/null | tr '\n' ' ' || true)
      printf '  %s  serial=%s  port=%s\n' "$model" "$serial" "$(basename "$dev")"
      if [ -n "$links" ]; then
        printf '        %s\n' "$links"
      fi
      ;;
  esac
done

echo ""
echo "[✓] 完成。应用层请改用 /dev/realsense/ 下的路径，"
echo "    例如 /dev/realsense/D405-334323070212-video0（先看上面的实际名字）"
