#!/usr/bin/env python3
"""机械臂控制核心模块，兼容 CLI 脚本和 Web 控制。

运动方式说明:
  - 使用 RealMan JSON 协议的 movel 指令做笛卡尔直线运动，
    保证沿 X/Y/Z 单轴直线移动（movej 是关节空间运动，路径会弯曲）。
  - 每次移动都以机械臂当前实际位姿(get_current_arm_state)为基准叠加增量，
    得到绝对目标位姿，因此多次移动不会累积误差。
"""

import json
import math
import os
import socket
import time
from typing import Dict, List, Optional


def _round_xyz(values: List[float]) -> List[float]:
    return [round(float(v), 3) for v in values]


try:
    from alphabot import ArmKinematics, ArmType, AbcErrorCode, Pose, Position, Quaternion
    HAS_SDK = True
except ImportError:
    ArmKinematics = ArmType = AbcErrorCode = Pose = Position = Quaternion = None
    HAS_SDK = False


def _env_flag(name: str) -> Optional[bool]:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_success(result) -> bool:
    """兼容 SDK 枚举(AbcErrorCode.SUCCESS)与旧式整数返回值(0)。"""
    if result is None:
        return False
    try:
        if result == getattr(AbcErrorCode, "SUCCESS", None):
            return True
    except Exception:
        pass
    return isinstance(result, int) and result == 0


def _quat_to_euler(w, x, y, z):
    """四元数 -> 欧拉角(rx, ry, rz)，与 RealMan ZYX/RPY 约定一致。"""
    rx = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    ry = math.asin(sp)
    rz = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return rx, ry, rz


def _euler_to_quat(rx, ry, rz):
    """欧拉角(rx, ry, rz 弧度) -> 四元数(w, x, y, z)，RealMan ZYX/RPY 约定。"""
    cx, sx = math.cos(rx / 2.0), math.sin(rx / 2.0)
    cy, sy = math.cos(ry / 2.0), math.sin(ry / 2.0)
    cz, sz = math.cos(rz / 2.0), math.sin(rz / 2.0)
    w = cx * cy * cz + sx * sy * sz
    x = sx * cy * cz - cx * sy * sz
    y = cx * sy * cz + sx * cy * sz
    z = cx * cy * sz - sx * sy * cz
    return w, x, y, z


class ArmController:
    """轻量化机械臂控制器，支持真实连接和模拟模式。"""

    JOINT4_LIMIT_DEG = -5.0

    def __init__(self, arm_name: str = "left", ip: Optional[str] = None, port: int = 8080, simulate: bool = False):
        self.arm_name = arm_name
        self.ip = ip or os.getenv(
            "LEFT_ARM_IP" if arm_name == "left" else "RIGHT_ARM_IP",
            "192.168.1.18" if arm_name == "left" else "192.168.1.19",
        )
        self.port = port or int(os.getenv("ARM_PORT", "8080"))
        self.simulate = simulate
        self._sock: Optional[socket.socket] = None
        self._kin = None
        self._joints: List[float] = [0.0] * 7
        self._position: List[float] = [0.0, 0.0, 0.0]
        self._orientation: List[float] = [0.0, 0.0, 0.0]  # rx,ry,rz 弧度
        self._initial_joints: Optional[List[float]] = None
        self._initial_position: List[float] = self._position[:]
        self._initial_orientation: List[float] = self._orientation[:]
        self._state_initialized = False
        self.connected = False
        self.last_error: Optional[str] = None
        self.last_warning: Optional[str] = None

    def connect(self) -> bool:
        if self.connected and self._sock is not None:
            return True

        if self.simulate:
            self.connected = True
            self.last_error = None
            if HAS_SDK:
                try:
                    arm_type = ArmType.ZM73R_6F if self.arm_name == "right" else ArmType.ZM73L_6F
                    self._kin = ArmKinematics.create(arm_type)
                except Exception:
                    self._kin = None
            print(f"ℹ️ 模拟模式（未连接真实机械臂）: {self.arm_name}")
            return True

        try:
            self._sock = socket.create_connection((self.ip, self.port), timeout=2.0)
            self._sock.settimeout(1.0)
            self.connected = True
            self.last_error = None
            print(f"✅ 已连接到 {self.ip}:{self.port}")
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            print(f"⚠️ 连接失败 {self.ip}:{self.port} - {exc}")
            return False

        if HAS_SDK:
            try:
                arm_type = ArmType.ZM73R_6F if self.arm_name == "right" else ArmType.ZM73L_6F
                self._kin = ArmKinematics.create(arm_type)
                print("✅ SDK 运动学已加载")
            except Exception as exc:
                self.last_error = str(exc)
                print(f"⚠️ SDK 运动学加载失败: {exc}")
        else:
            print("⚠️ 未找到 alphabot SDK，位姿读取将依赖机械臂协议")

        self._refresh_state()
        return True

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self.connected = False

    def _send_recv(self, cmd: Dict[str, object], timeout: float = 1.0) -> Optional[Dict[str, object]]:
        if not self._sock:
            return None
        try:
            self._sock.sendall((json.dumps(cmd) + "\r\n").encode("utf-8"))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    self._sock.settimeout(0.2)
                    data = self._sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    continue
                for line in data.decode("utf-8", errors="ignore").strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        resp = json.loads(line)
                        if isinstance(resp, dict):
                            return resp
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            self.last_error = str(exc)
            print(f"❌ 通信异常: {exc}")
        return None

    def _normalize_joint_values(self, values: List[object]) -> Optional[List[float]]:
        if not isinstance(values, list) or not values:
            return None
        try:
            normalized = [float(v) for v in values]
        except (TypeError, ValueError):
            return None
        # 协议关节精度 0.001°，数值较大时需缩放
        if any(abs(v) > 360 for v in normalized):
            return [v / 1000.0 for v in normalized]
        return normalized

    def _extract_joint_values(self, resp: dict) -> Optional[List[float]]:
        keys = ("joint_status", "joint", "joints", "joint_angle", "joint_cur", "data", "joint_data", "joint_degree", "joint_angles")
        for key in keys:
            value = resp.get(key)
            if isinstance(value, list):
                normalized = self._normalize_joint_values(value)
                if normalized is not None:
                    return normalized
            if isinstance(value, dict):
                nested = self._extract_joint_values(value)
                if nested is not None:
                    return nested
        return None

    def get_joint_degree(self) -> Optional[List[float]]:
        resp = self._send_recv({"command": "get_joint_degree"})
        if resp is None:
            return None
        arm_state = resp.get("arm_state")
        if isinstance(arm_state, dict):
            joints = self._extract_joint_values(arm_state)
            if joints is not None:
                return joints
        return self._extract_joint_values(resp)

    def _normalize_pose_values(self, values: List[object]) -> Optional[List[float]]:
        """协议位姿 -> [x,y,z,rx,ry,rz]，单位 m/rad。"""
        if not isinstance(values, list) or len(values) < 6:
            return None
        try:
            p = [float(v) for v in values[:6]]
        except (TypeError, ValueError):
            return None
        # 姿态已为弧度(<2π)时，认为位置已是米，直接返回
        if all(abs(v) < 6.5 for v in p[3:]):
            return p
        # 协议整数格式：位置 0.001mm，姿态 0.001rad
        return [
            p[0] * 1e-6, p[1] * 1e-6, p[2] * 1e-6,
            p[3] * 1e-3, p[4] * 1e-3, p[5] * 1e-3,
        ]

    def _pose_from_resp(self, resp: Optional[dict]) -> Optional[List[float]]:
        if resp is None:
            return None
        pose = None
        arm_state = resp.get("arm_state")
        if isinstance(arm_state, dict):
            pose = arm_state.get("pose")
        if pose is None:
            pose = resp.get("pose")
        if isinstance(pose, list):
            return self._normalize_pose_values(pose)
        return None

    def get_current_pose(self) -> Optional[List[float]]:
        """返回 [x,y,z,rx,ry,rz]（m/rad），失败返回 None。"""
        if self.simulate:
            return self._position[:] + self._orientation[:]
        resp = self._send_recv({"command": "get_current_arm_state"})
        pose = self._pose_from_resp(resp)
        if pose is None:
            joints = self.get_joint_degree()
            if joints and self._kin is not None:
                try:
                    result, fk = self._kin.forward_kinematics([math.radians(v) for v in joints])
                    if _is_success(result):
                        rx, ry, rz = _quat_to_euler(
                            fk.quaternion.w, fk.quaternion.x, fk.quaternion.y, fk.quaternion.z
                        )
                        pose = [float(fk.position.x), float(fk.position.y), float(fk.position.z), rx, ry, rz]
                except Exception:
                    pose = None
        return pose

    def check_joint4_limit(self, target_pose: List[float], limit_deg: float = -5.0) -> tuple:
        """IK 校验目标位姿的关节4目标角度是否超过限位。

        返回 (是否允许执行, 关节4目标角度或 None)。逆解失败时返回不允许，
        确保无法校验限位时也不执行，避免机械臂自行规划到超限位姿。
        """
        if self.simulate or not target_pose or len(target_pose) < 6:
            return True, None
        joints = self.get_joint_degree() or self._joints
        if not joints:
            return True, None
        if self._kin is None:
            # 无 SDK 时无法校验，交由机械臂自身判断
            return True, None
        try:
            pose = Pose()
            pose.position = Position()
            pose.position.x, pose.position.y, pose.position.z = target_pose[:3]
            qw, qx, qy, qz = _euler_to_quat(target_pose[3], target_pose[4], target_pose[5])
            pose.quaternion = Quaternion()
            pose.quaternion.w, pose.quaternion.x, pose.quaternion.y, pose.quaternion.z = qw, qx, qy, qz
            err, sol = self._kin.inverse_kinematics(pose, [math.radians(v) for v in joints], 0)
            if _is_success(err) and sol and len(sol) > 3:
                j4 = math.degrees(sol[3])
                return j4 <= limit_deg, j4
        except Exception:
            pass
        # IK 求解失败：无法确认关节4目标角度，一律不执行
        return False, None

    def _refresh_state(self) -> None:
        if self.simulate:
            return
        resp = self._send_recv({"command": "get_current_arm_state"}) if self._sock else None
        pose = self._pose_from_resp(resp)
        joints = None
        if resp is not None:
            arm_state = resp.get("arm_state")
            if isinstance(arm_state, dict):
                joints = self._extract_joint_values(arm_state)
            if joints is None:
                joints = self._extract_joint_values(resp)
        if pose is None:
            joints = joints or self.get_joint_degree()
            if joints and self._kin is not None:
                try:
                    result, fk = self._kin.forward_kinematics([math.radians(v) for v in joints])
                    if _is_success(result):
                        rx, ry, rz = _quat_to_euler(
                            fk.quaternion.w, fk.quaternion.x, fk.quaternion.y, fk.quaternion.z
                        )
                        pose = [float(fk.position.x), float(fk.position.y), float(fk.position.z), rx, ry, rz]
                except Exception:
                    pose = None
        if joints:
            self._joints = joints
            if self._initial_joints is None:
                self._initial_joints = joints[:]
        if pose:
            self._position = pose[:3]
            self._orientation = pose[3:]
            if not self._state_initialized:
                self._initial_position = pose[:3]
                self._initial_orientation = pose[3:]
                self._state_initialized = True

    def _wait_completion(self, timeout: float = 8.0, grace: float = 1.0) -> bool:
        """等待 receive_state 与 current_trajectory_state 返回。

        部分固件不回 current_trajectory_state，收到 receive_state=true 后再宽限
        grace 秒即认为完成，避免每次操作长时间阻塞。
        """
        if not self._sock:
            return False
        deadline = time.monotonic() + timeout
        accepted = None
        accepted_at = None
        while time.monotonic() < deadline:
            if accepted and accepted_at is not None and time.monotonic() - accepted_at >= grace:
                return True
            try:
                self._sock.settimeout(0.2)
                data = self._sock.recv(4096)
            except socket.timeout:
                continue
            except Exception as exc:
                self.last_error = str(exc)
                break
            if not data:
                continue
            for line in data.decode("utf-8", errors="ignore").strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(p, dict):
                    continue
                if "receive_state" in p:
                    accepted = p.get("receive_state") in (True, "true", 1, "1")
                    if not accepted:
                        self.last_error = f"指令被拒绝: {json.dumps(p, ensure_ascii=False)}"
                        return False
                    accepted_at = time.monotonic()
                if p.get("state") == "current_trajectory_state" or "trajectory_state" in p:
                    ok = p.get("trajectory_state") in (True, "true", 1, "1")
                    if not ok:
                        self.last_error = f"运动未完成: {json.dumps(p, ensure_ascii=False)}"
                    return ok
        if accepted:
            return True
        if not self.last_error:
            self.last_error = "等待指令应答超时"
        return False

    def move_pose(self, pose: List[float], speed: float = 10.0, timeout: float = 8.0) -> bool:
        """发送 movel 直线运动并等待完成。pose: [x,y,z,rx,ry,rz] m/rad。"""
        if self.simulate:
            self._position = pose[:3]
            self._orientation = pose[3:]
            return True
        if not self._sock:
            return False
        pose_cmd = [
            int(round(pose[0] * 1e6)), int(round(pose[1] * 1e6)), int(round(pose[2] * 1e6)),
            int(round(pose[3] * 1e3)), int(round(pose[4] * 1e3)), int(round(pose[5] * 1e3)),
        ]
        cmd = {
            "command": "movel", "pose": pose_cmd,
            "v": int(speed), "r": 0, "trajectory_connect": 0, "block": 1,
        }
        try:
            self._sock.sendall((json.dumps(cmd) + "\r\n").encode("utf-8"))
            return self._wait_completion(timeout)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"❌ move_pose 异常: {exc}")
            return False

    def move_joints(self, joints_deg: List[float], speed: int = 20, timeout: float = 8.0) -> bool:
        """发送阻塞式关节移动命令 (movej)，用于复位回退。"""
        if self.simulate:
            self._joints = [float(v) for v in joints_deg]
            return True
        if not self._sock:
            return False
        joint_cmd = [int(round(j * 1000)) for j in joints_deg]
        cmd = {
            "command": "movej", "joint": joint_cmd,
            "v": int(speed), "r": 0, "trajectory_connect": 0, "block": 1,
        }
        try:
            self._sock.sendall((json.dumps(cmd) + "\r\n").encode("utf-8"))
            return self._wait_completion(timeout)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"❌ move_joints 异常: {exc}")
            return False

    def move(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0, speed: float = 10.0) -> Dict[str, object]:
        """基于笛卡尔增量的直线运动：目标 = 当前实际位姿 + 增量，movel 执行。

        入参 dx/dy/dz 统一为“物理坐标”增量（与左臂按键方向一致）：
          X=上/下、Y=前/后(深/浅)、Z=左/右。
        右臂 ZM73R 是左臂 ZM73L 的镜像型号，右臂自身基坐标系与左臂互为镜像
        （物理上 X 同向、Y/Z 反向），因此右臂执行前要把物理增量换算成
        右臂自身基坐标系增量（Y、Z 取反）。
        """
        dx = float(dx)
        dy = float(dy)
        dz = float(dz)
        if self.arm_name == "right":
            dx, dy, dz = dx, -dy, -dz
        if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
            self._refresh_state()
            return self.get_state()

        # 以机械臂实际位姿为基准，避免多次移动累计误差
        self._refresh_state()
        if self.simulate:
            self._position = [self._position[0] + dx, self._position[1] + dy, self._position[2] + dz]
            return self.get_state()

        target = [
            self._position[0] + dx,
            self._position[1] + dy,
            self._position[2] + dz,
            self._orientation[0],
            self._orientation[1],
            self._orientation[2],
        ]
        # 机械臂限位校验：IK 求解关节4目标角度，超过 -5° 不执行
        self.last_error = None
        self.last_warning = None
        allow, j4 = self.check_joint4_limit(target)
        if not allow:
            if j4 is None:
                self.last_error = "IK 求解失败，无法校验关节4限位，移动已取消"
            else:
                self.last_error = f"关节4目标角度 {j4:.2f}° 超过限位 -5°，移动已取消"
            return self.get_state()
        ok = self.move_pose(target, speed=speed)
        if ok:
            self._position = target[:3]
            self._orientation = target[3:]
        self._refresh_state()
        # 移动后实测关节4做二次校验（防止机械臂规划分支与校验不一致）。
        # 移动本身已成功，只给出告警，不把结果误报为失败。
        if ok and not self.simulate and len(self._joints) > 3 and self._joints[3] > self.JOINT4_LIMIT_DEG:
            self.last_warning = (
                f"移动已执行，但关节4实际角度 {self._joints[3]:.2f}° 仍超过限位 -5°，请立即复位检查"
            )
        if not ok and not self.last_error:
            self.last_error = "movel 执行失败（目标可能超出工作空间）"
        return self.get_state()

    def reset(self) -> Dict[str, object]:
        """复位到初始位姿：优先 movel 直线运动，失败时回退 movej。"""
        if self.simulate:
            self._position = self._initial_position[:]
            self._orientation = self._initial_orientation[:]
            if self._initial_joints is not None:
                self._joints = self._initial_joints[:]
            return self.get_state()

        ok = False
        # 初始位姿未成功捕获时禁止向原点 movel（避免复位到未知姿态）
        if self._state_initialized:
            init_pose = self._initial_position[:] + self._initial_orientation[:]
            ok = self.move_pose(init_pose, speed=20.0, timeout=10.0)
        if not ok and self._initial_joints is not None:
            ok = self.move_joints(self._initial_joints[:], speed=20, timeout=10.0)
        self._refresh_state()
        if not ok:
            self.last_error = self.last_error or (
                "初始位姿未初始化，无法复位" if self._initial_joints is None else "复位失败"
            )
        return self.get_state()

    def emergency_stop(self) -> Dict[str, object]:
        """发送缓停指令（set_arm_slow_stop）。"""
        if self.simulate or not self._sock:
            return self.get_state()
        try:
            self._sock.sendall((json.dumps({"command": "set_arm_slow_stop"}) + "\r\n").encode("utf-8"))
        except Exception as exc:
            self.last_error = str(exc)
        return self.get_state()

    def get_state(self) -> Dict[str, object]:
        position = _round_xyz(self._position)
        initial_position = _round_xyz(self._initial_position)
        delta = _round_xyz([self._position[i] - self._initial_position[i] for i in range(3)])
        if self.arm_name == "right":
            # 右臂状态按物理坐标输出（X 同向、Y/Z 反向），与左臂/按键方向保持一致
            position = _round_xyz([position[0], -position[1], -position[2]])
            initial_position = _round_xyz([initial_position[0], -initial_position[1], -initial_position[2]])
            delta = _round_xyz([delta[0], -delta[1], -delta[2]])
        return {
            "connected": self.connected or self.simulate,
            "simulate": self.simulate,
            "arm_name": self.arm_name,
            "joints": [round(float(v), 3) for v in self._joints],
            "position": position,
            "orientation": _round_xyz(self._orientation),
            "initial_position": initial_position,
            "delta": delta,
            "error": self.last_error,
            "warning": self.last_warning,
        }


if __name__ == "__main__":
    controller = ArmController()
    controller.connect()
    print(controller.get_state())
    controller.disconnect()
