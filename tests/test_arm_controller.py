import importlib.util
import math
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("arm_controller", ROOT / "arm_controller.py")
arm_controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arm_controller)

# 无 alphabot SDK 时，为 IK 校验注入最小可用的 Pose/Position/Quaternion 替身，
# 保证限位校验用例在纯标准库环境也能运行。
if not arm_controller.HAS_SDK:
    class _FakePosition:
        def __init__(self):
            self.x = self.y = self.z = 0.0

    class _FakeQuaternion:
        def __init__(self):
            self.w = self.x = self.y = self.z = 0.0

    class _FakePose:
        def __init__(self):
            self.position = _FakePosition()
            self.quaternion = _FakeQuaternion()

    arm_controller.Pose = _FakePose
    arm_controller.Position = _FakePosition
    arm_controller.Quaternion = _FakeQuaternion


class ArmControllerTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ARM_SIMULATE", None)

    def test_ignore_arm_simulate_env(self):
        os.environ["ARM_SIMULATE"] = "1"
        controller = arm_controller.ArmController(arm_name="left")
        self.assertFalse(controller.simulate)

    def test_state_values_are_rounded_to_three_decimals(self):
        controller = arm_controller.ArmController(arm_name="left")
        controller._position = [0.1234567, -0.0009999, 0.0100101]
        controller._initial_position = [0.0, 0.0, 0.0]

        state = controller.get_state()

        self.assertEqual(state["position"], [0.123, -0.001, 0.01])
        self.assertEqual(state["delta"], [0.123, -0.001, 0.01])

    def test_move_sends_movel_target_from_actual_pose_plus_delta(self):
        """movel 目标必须以当前实际位姿为基准叠加增量，而不是初始位姿。"""
        controller = arm_controller.ArmController(arm_name="left")
        controller._position = [0.1, 0.2, 0.3]
        controller._orientation = [0.4, 0.5, 0.6]
        controller._initial_position = [0.0, 0.0, 0.0]
        controller._joints = [0.0] * 7

        with mock.patch.object(controller, "_refresh_state"), \
             mock.patch.object(controller, "move_pose", return_value=True) as move_pose:
            controller.move(dx=0.01, dy=0.0, dz=0.0)

        self.assertTrue(move_pose.called)
        target = move_pose.call_args[0][0]
        self.assertEqual(target[:3], [0.11, 0.2, 0.3])
        self.assertEqual(target[3:], [0.4, 0.5, 0.6])

    def test_move_accumulates_delta_for_repeated_calls(self):
        """连续两次同方向移动必须累积位移，而不是每次从初始位姿重算。"""
        controller = arm_controller.ArmController(arm_name="left")
        controller._position = [0.1, 0.2, 0.3]
        controller._orientation = [0.0, 0.0, 0.0]
        controller._initial_position = [0.0, 0.0, 0.0]
        controller._joints = [0.0] * 7

        with mock.patch.object(controller, "_refresh_state"), \
             mock.patch.object(controller, "move_pose", return_value=True):
            controller.move(dx=0.01, dy=0.0, dz=0.0)
            controller.move(dx=0.01, dy=0.0, dz=0.0)

        self.assertAlmostEqual(controller._position[0], 0.12, places=6)
        self.assertAlmostEqual(controller.get_state()["delta"][0], 0.12, places=6)

    def test_reset_moves_back_to_initial_pose(self):
        """复位必须实际发送运动指令回到初始位姿。"""
        controller = arm_controller.ArmController(arm_name="left")
        controller._initial_position = [0.1, 0.2, 0.3]
        controller._initial_orientation = [0.0, 0.0, 0.0]
        controller._initial_joints = [0.0] * 7
        controller._position = [0.5, 0.5, 0.5]
        controller._orientation = [0.0, 0.0, 0.0]
        controller._state_initialized = True

        with mock.patch.object(controller, "move_pose", return_value=True) as move_pose, \
             mock.patch.object(controller, "_refresh_state"):
            controller.reset()

        self.assertTrue(move_pose.called)
        target = move_pose.call_args[0][0]
        self.assertEqual(target[:3], [0.1, 0.2, 0.3])

    def test_reset_refuses_when_initial_state_unknown(self):
        """初始位姿从未成功捕获时，复位必须拒绝执行，不能向原点/零关节下发。"""
        controller = arm_controller.ArmController(arm_name="left")
        controller._initial_joints = None
        controller._state_initialized = False

        with mock.patch.object(controller, "move_pose", return_value=True) as move_pose, \
             mock.patch.object(controller, "move_joints", return_value=True) as move_joints, \
             mock.patch.object(controller, "_refresh_state"):
            state = controller.reset()

        self.assertFalse(move_pose.called)
        self.assertFalse(move_joints.called)
        self.assertIn("初始位姿", state["error"])

    def test_move_warns_but_keeps_result_when_joint4_over_limit_after_move(self):
        """移动成功后实测关节4超限：移动本身已完成，只报告警，不误报失败。"""
        controller = arm_controller.ArmController(arm_name="left")
        controller._joints = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # J4=0° > -5°
        controller._position = [0.1, 0.2, 0.3]
        controller._orientation = [0.0, 0.0, 0.0]
        controller._initial_position = [0.0, 0.0, 0.0]
        controller._kin = None

        with mock.patch.object(controller, "_refresh_state"), \
             mock.patch.object(controller, "move_pose", return_value=True) as move_pose:
            state = controller.move(dx=0.01, dy=0.0, dz=0.0)

        self.assertTrue(move_pose.called)
        self.assertFalse(state["error"])
        self.assertIn("关节4", state["warning"])

    def test_move_blocked_when_joint4_exceeds_limit(self):
        """关节4目标角度 > -5° 时不执行移动并返回限位错误。"""
        class FakeKin:
            def __init__(self, j4_deg=None, fail=False):
                self.j4_deg = j4_deg
                self.fail = fail

            def inverse_kinematics(self, pose, seed, mode):
                if self.fail:
                    return -107, []
                sol = [0.0] * 7
                sol[3] = math.radians(self.j4_deg)
                return 0, sol

        controller = arm_controller.ArmController(arm_name="left")
        controller._joints = [0.0] * 7
        controller._position = [0.1, 0.2, 0.3]
        controller._orientation = [0.0, 0.0, 0.0]
        controller._initial_position = [0.0, 0.0, 0.0]

        with mock.patch.object(controller, "_refresh_state"), \
             mock.patch.object(controller, "move_pose", return_value=True) as move_pose:
            # J4 = -3° > -5°，应拦截
            controller._kin = FakeKin(-3.0)
            state = controller.move(dx=0.01, dy=0.0, dz=0.0)
            self.assertFalse(move_pose.called)
            self.assertIn("限位", state["error"])
            self.assertIn("关节4", state["error"])

            # IK 求解失败 → 无法校验限位，也应拦截
            controller._kin = FakeKin(fail=True)
            state = controller.move(dx=0.01, dy=0.0, dz=0.0)
            self.assertFalse(move_pose.called)
            self.assertIn("IK 求解失败", state["error"])

            # J4 = -8° <= -5°，应放行
            controller._kin = FakeKin(-8.0)
            controller._joints = [0.0, 0.0, 0.0, -8.0, 0.0, 0.0, 0.0]
            state = controller.move(dx=0.01, dy=0.0, dz=0.0)
            self.assertTrue(move_pose.called)
            self.assertFalse(state["error"])

    def test_quat_to_euler_matches_realman_convention(self):
        """四元数转欧拉角需符合 RealMan ZYX/RPY 约定。"""
        # 绕 X 轴旋转 90°
        q = (math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0, 0.0)
        rx, ry, rz = arm_controller._quat_to_euler(*q)
        self.assertAlmostEqual(rx, math.pi / 2, places=6)
        self.assertAlmostEqual(ry, 0.0, places=6)
        self.assertAlmostEqual(rz, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
