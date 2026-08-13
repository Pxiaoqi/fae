#!/usr/bin/env python3
"""
机械臂键盘控制 - 笛卡尔空间微调（基于 Socket + RealMan movel 协议）

用法:
  python3 arm-true.py <left|right> [--ip 192.168.1.18] [--port 8080] [--step 0.01] [--speed 20]

按键（与 Web 控制台一致，物理坐标）:
  W/S : Y 轴（深/浅）
  A/D : Z 轴（左/右）
  Q/E : X 轴（上/下）
  R   : 复位到初始位姿
  F   : 显示当前关节角度
  T   : 显示当前末端位移量（相对于初始点）
  Space : 紧急停止
  Esc  : 退出

说明:
  复用 arm_controller.ArmController，与 Web 控制台共享运动学、关节4限位校验
  与右臂 Y/Z 镜像换算，避免两份实现漂移。
"""

import argparse
import os
import select
import sys
import termios
import tty
from typing import Optional

from arm_controller import ArmController

ARM_PORT = int(os.getenv("ARM_PORT", "8080"))


def read_key(timeout: float = 0.1) -> Optional[str]:
    """非阻塞读取单个按键。"""
    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="机械臂键盘控制脚本")
    parser.add_argument("arm", choices=["left", "right"], help="选择机械臂")
    parser.add_argument("--ip", default=None, help="机械臂 IP")
    parser.add_argument("--port", type=int, default=ARM_PORT, help="机械臂端口")
    parser.add_argument("--step", type=float, default=0.01, help="单次移动步长")
    parser.add_argument("--speed", type=float, default=10.0, help="运动速度")
    return parser


def _format_state(state: dict, mode: str = "all") -> str:
    """把 get_state() 的返回格式化为终端可读文本。"""
    lines = []
    if mode in {"joints", "all"}:
        joints = [f"{v:.3f}" for v in state.get("joints", [])]
        lines.append(f"关节角度: {joints}")
    if mode in {"pose", "all"}:
        pos = state.get("position", [0.0, 0.0, 0.0])
        delta = state.get("delta", [0.0, 0.0, 0.0])
        lines.append(
            f"末端位置: X={pos[0]:.3f} Y={pos[1]:.3f} Z={pos[2]:.3f} "
            f"| 相对初始位移: X={delta[0]:.3f} Y={delta[1]:.3f} Z={delta[2]:.3f}"
        )
    err = state.get("error") or state.get("warning")
    if err:
        lines.append(f"⚠️ {err}")
    return "\n".join(lines)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    default_ip = os.getenv("LEFT_ARM_IP", "192.168.1.18")
    if args.arm == "right":
        default_ip = os.getenv("RIGHT_ARM_IP", "192.168.1.19")
    args.ip = args.ip or default_ip

    controller = ArmController(args.arm, args.ip, args.port, simulate=False)
    print("=== 机械臂键盘控制 ===")
    print("按键说明: W/S=Y 深/浅, A/D=Z 左/右, Q/E=X 上/下, R 复位, F 查看关节, T 查看位移, Space 急停, Esc 退出")

    if not controller.connect():
        return 1

    print("当前状态:")
    print(_format_state(controller.get_state(), "all"))

    try:
        while True:
            key = read_key(0.1)
            if key is None:
                continue
            if key == "\x1b":
                break
            if key.lower() == "w":
                state = controller.move(dy=args.step, speed=args.speed)
            elif key.lower() == "s":
                state = controller.move(dy=-args.step, speed=args.speed)
            elif key.lower() == "a":
                state = controller.move(dz=args.step, speed=args.speed)
            elif key.lower() == "d":
                state = controller.move(dz=-args.step, speed=args.speed)
            elif key.lower() == "q":
                state = controller.move(dx=args.step, speed=args.speed)
            elif key.lower() == "e":
                state = controller.move(dx=-args.step, speed=args.speed)
            elif key.lower() == "r":
                state = controller.reset()
            elif key.lower() == "f":
                print(_format_state(controller.get_state(), "joints"))
                continue
            elif key.lower() == "t":
                print(_format_state(controller.get_state(), "pose"))
                continue
            elif key == " ":
                state = controller.emergency_stop()
            else:
                print("未识别按键，按键说明: W/S=Y 深/浅, A/D=Z 左/右, Q/E=X 上/下, R 复位, F 查看关节, T 查看位移, Space 急停, Esc 退出")
                continue
            print(_format_state(state, "pose"))
    except KeyboardInterrupt:
        print("\n已中断")
    finally:
        controller.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
