import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("arm_config_utils", ROOT / "arm_config_utils.py")
arm_config_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arm_config_utils)


class ArmConfigHelperTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ARM_DOCKER_CONTAINER", None)

    def test_read_text_file_from_docker_container(self):
        os.environ["ARM_DOCKER_CONTAINER"] = "demo-container"

        def fake_run(cmd, capture_output, text, check, input=None):
            self.assertEqual(cmd[0], "docker")
            self.assertEqual(cmd[1], "exec")
            self.assertEqual(cmd[2], "demo-container")
            self.assertEqual(cmd[3], "cat")
            self.assertEqual(cmd[4], "/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml")
            return subprocess.CompletedProcess(cmd, 0, stdout="hello: world\n", stderr="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            helper = arm_config_utils.ArmConfigHelper(arm_config_path="/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml")
            result = helper.read_text_file("/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml")

        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "hello: world\n")

    def test_list_directory_from_docker_container(self):
        os.environ["ARM_DOCKER_CONTAINER"] = "demo-container"

        def fake_run(cmd, capture_output, text, check, input=None):
            self.assertEqual(cmd[:3], ["docker", "exec", "demo-container"])
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps([{"name": "ARM.yaml", "path": "/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml", "is_dir": False, "is_file": True}]), stderr="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            helper = arm_config_utils.ArmConfigHelper(arm_config_path="/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml")
            result = helper.list_directory("/root/AlphaBrainSystem/configs/behavior/COFFEE")

        self.assertTrue(result["ok"] if "ok" in result else True)
        self.assertEqual(result["entries"][0]["name"], "ARM.yaml")

    def test_reads_from_docker_after_environment_is_set(self):
        os.environ.pop("ARM_DOCKER_CONTAINER", None)
        os.environ.pop("ARM_CONFIG_PATH", None)
        helper = arm_config_utils.ArmConfigHelper(arm_config_path="/tmp/local.yaml")

        os.environ["ARM_DOCKER_CONTAINER"] = "demo-container"
        os.environ["ARM_CONFIG_PATH"] = "/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml"

        def fake_run(cmd, capture_output, text, check, input=None):
            self.assertEqual(cmd[0], "docker")
            self.assertEqual(cmd[2], "demo-container")
            self.assertEqual(cmd[4], "/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml")
            return subprocess.CompletedProcess(cmd, 0, stdout="hello: world\n", stderr="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            result = helper.read_text_file("/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml")

        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "hello: world\n")

    def test_local_sentinel_overrides_docker_env(self):
        """__local__ 哨兵必须绕过环境变量默认容器，按本机文件处理。"""
        os.environ["ARM_DOCKER_CONTAINER"] = "demo-container"
        tmpdir = tempfile.mkdtemp(prefix="arm_local_")
        self.addCleanup(shutil.rmtree, tmpdir)
        helper = arm_config_utils.ArmConfigHelper(
            base_dir=tmpdir,
            arm_config_path=os.path.join(tmpdir, "ARM.yaml"),
        )

        with mock.patch("subprocess.run") as mocked:
            result = helper.read_text_file(os.path.join(tmpdir, "ARM.yaml"), container=arm_config_utils.LOCAL_SENTINEL)

        mocked.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "file_not_found")


class ArmConfigHelperCrossBlockTests(unittest.TestCase):
    """同一 node 在 ARM.yaml 中出现多个独立块时，occurrence 要能跨块定位。"""

    def tearDown(self):
        os.environ.pop("ARM_DOCKER_CONTAINER", None)
        os.environ.pop("ARM_CONFIG_PATH", None)

    def _make_helper(self, content):
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        self.addCleanup(os.unlink, path)
        return arm_config_utils.ArmConfigHelper(arm_config_path=path), path

    def test_get_action_value_finds_occurrence_across_blocks(self):
        content = (
            "move_left_arm_to_place_cup_B:\n"
            "  approach_distance: [0.1, 0.2, 0.3]\n"
            "move_left_arm_to_place_cup_B:\n"
            "  approach_distance: [0.4, 0.5, 0.6]\n"
        )
        helper, _ = self._make_helper(content)
        act = {"node": "move_left_arm_to_place_cup_B", "param": "approach_distance", "occurrence": 2}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.get_action_value("x")

        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], [[0.4, 0.5, 0.6]])

    def test_update_action_value_updates_second_occurrence_only(self):
        content = (
            "move_left_arm_to_place_cup_B:\n"
            "  approach_distance: [0.1, 0.2, 0.3]\n"
            "move_left_arm_to_place_cup_B:\n"
            "  approach_distance: [0.4, 0.5, 0.6]\n"
        )
        helper, path = self._make_helper(content)
        act = {"node": "move_left_arm_to_place_cup_B", "param": "approach_distance", "occurrence": 2}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.update_action_value("x", [[0.7, 0.8, 0.9]])

        self.assertTrue(result["ok"])
        with open(path, "r", encoding="utf-8") as fh:
            updated = fh.read()
        self.assertIn("approach_distance: [0.1, 0.2, 0.3]", updated)
        self.assertIn("approach_distance: [0.7, 0.8, 0.9]", updated)
        self.assertNotIn("0.4", updated)


class ActiveBehaviorTreeTests(unittest.TestCase):
    """PIPELINE.yaml 的 active_behavior_tree 解析与动作分组过滤。"""

    def tearDown(self):
        os.environ.pop("ARM_DOCKER_CONTAINER", None)
        os.environ.pop("ARM_CONFIG_PATH", None)

    def _make_helper(self, pipeline_content=None):
        tmpdir = tempfile.mkdtemp(prefix="arm_pipeline_")
        self.addCleanup(shutil.rmtree, tmpdir)
        if pipeline_content is not None:
            with open(os.path.join(tmpdir, "PIPELINE.yaml"), "w", encoding="utf-8") as fh:
                fh.write(pipeline_content)
        return arm_config_utils.ArmConfigHelper(arm_config_path=os.path.join(tmpdir, "ARM.yaml"))

    def test_parses_robot_letter_and_device(self):
        helper = self._make_helper('active_behavior_tree: "RobotC"  # 可选：RobotA、RobotB...\n')
        result = helper.get_active_behavior_tree()
        self.assertTrue(result["ok"])
        self.assertEqual(result["value"], "RobotC")
        self.assertEqual(result["robot_letter"], "C")
        self.assertEqual(result["device"], "ice_cream")
        self.assertEqual(result["label"], "冰激凌机")

    def test_parses_lkf_variant_as_base_robot(self):
        helper = self._make_helper("active_behavior_tree: RobotE_LKF\n")
        result = helper.get_active_behavior_tree()
        self.assertTrue(result["ok"])
        self.assertEqual(result["robot_letter"], "E")
        self.assertEqual(result["device"], "beer")
        self.assertEqual(result["label"], "啤酒机")

    def test_missing_pipeline_returns_not_ok(self):
        helper = self._make_helper()
        result = helper.get_active_behavior_tree()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "pipeline_not_found")

    def test_list_actions_filters_by_active_robot(self):
        helper = self._make_helper("active_behavior_tree: RobotE\n")
        result = helper.list_actions()
        self.assertEqual([dev["id"] for dev in result["tree"]], ["beer"])
        self.assertTrue(result["active_robot"]["ok"])
        self.assertEqual(list(result["config"].keys()), ["beer"])

    def test_list_actions_empty_for_unconfigured_robot(self):
        helper = self._make_helper("active_behavior_tree: RobotF\n")
        result = helper.list_actions()
        self.assertEqual(result["tree"], [])
        self.assertEqual(result["active_robot"]["label"], "鸡尾酒机")

    def test_list_actions_returns_all_when_pipeline_missing(self):
        helper = self._make_helper()
        result = helper.list_actions()
        self.assertGreater(len(result["tree"]), 1)
        self.assertFalse(result["active_robot"]["ok"])


class ActionPauseTests(unittest.TestCase):
    """TEMPLATE-*.yaml 中 120s 暂停节点的插入与切换迁移。"""

    def tearDown(self):
        os.environ.pop("ARM_DOCKER_CONTAINER", None)
        os.environ.pop("ARM_CONFIG_PATH", None)

    def _make_helper(self, template_content, robot="RobotC", template_name="TEMPLATE-C.yaml"):
        tmpdir = tempfile.mkdtemp(prefix="arm_pause_")
        self.addCleanup(shutil.rmtree, tmpdir)
        with open(os.path.join(tmpdir, "PIPELINE.yaml"), "w", encoding="utf-8") as fh:
            fh.write(f"active_behavior_tree: {robot}\n")
        with open(os.path.join(tmpdir, template_name), "w", encoding="utf-8") as fh:
            fh.write(template_content)
        return (
            arm_config_utils.ArmConfigHelper(
                base_dir=tmpdir,
                arm_config_path=os.path.join(tmpdir, "ARM.yaml"),
            ),
            tmpdir,
        )

    def _read_template(self, tmpdir, name="TEMPLATE-C.yaml"):
        with open(os.path.join(tmpdir, name), "r", encoding="utf-8") as fh:
            return fh.read()

    def test_inserts_pause_after_selected_node(self):
        content = (
            "behavior_tree_template:\n"
            '  "manip_cup":\n'
            "    children:\n"
            '      - "move_left_arm_to_place_cup_C"\n'
            '      - "move_left_arm_back_from_cup_popper"\n'
        )
        helper, tmpdir = self._make_helper(content)
        act = {"node": "move_left_arm_to_place_cup_C", "param": "approach_distance", "occurrence": 1}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.set_action_pause("x")

        self.assertTrue(result["ok"])
        self.assertEqual(result["pause"], "sleep_for_120s")
        updated = self._read_template(tmpdir)
        self.assertIn(
            '      - "move_left_arm_to_place_cup_C"\n      - "sleep_for_120s"',
            updated,
        )

    def test_moves_pause_when_switching_action(self):
        content = (
            "children:\n"
            '  - "move_left_arm_to_place_cup_C"\n'
            '  - "sleep_for_120s"\n'
            '  - "move_left_arm_back_from_cup_popper"\n'
        )
        helper, tmpdir = self._make_helper(content)
        act = {"node": "move_left_arm_back_from_cup_popper", "param": "approach_distance", "occurrence": 1}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.set_action_pause("x")

        self.assertTrue(result["ok"])
        updated = self._read_template(tmpdir)
        self.assertEqual(updated.count('"sleep_for_120s"'), 1)
        self.assertLess(
            updated.find('"move_left_arm_back_from_cup_popper"'),
            updated.find('"sleep_for_120s"'),
        )

    def test_uses_occurrence_to_pick_node(self):
        content = (
            "children:\n"
            '  - "move_left_arm_back_open_then_fetch_cup_from_cup_popper_C"\n'
            '  - "move_left_arm_back_open_then_fetch_cup_from_cup_popper_C"\n'
        )
        helper, tmpdir = self._make_helper(content)
        act = {"node": "move_left_arm_back_open_then_fetch_cup_from_cup_popper_C", "param": "approach_distance", "occurrence": 2}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.set_action_pause("x")

        self.assertTrue(result["ok"])
        updated = self._read_template(tmpdir)
        first = updated.find('"move_left_arm_back_open_then_fetch_cup_from_cup_popper_C"')
        second = updated.find('"move_left_arm_back_open_then_fetch_cup_from_cup_popper_C"', first + 1)
        pause = updated.find('"sleep_for_120s"')
        self.assertGreater(pause, second)

    def test_unique_template_node_falls_back_to_first_occurrence(self):
        """模板只引用一次、动作 occurrence 为 2 时，不再重复查找，直接命中唯一节点。"""
        content = (
            "children:\n"
            '  - "move_left_arm_back_open_then_fetch_cup_from_cup_popper_C"\n'
            '  - "move_left_arm_back_from_cup_popper"\n'
        )
        helper, tmpdir = self._make_helper(content)
        act = {"node": "move_left_arm_back_open_then_fetch_cup_from_cup_popper_C", "param": "approach_distance", "occurrence": 2}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.set_action_pause("x")

        self.assertTrue(result["ok"])
        updated = self._read_template(tmpdir)
        self.assertIn(
            '  - "move_left_arm_back_open_then_fetch_cup_from_cup_popper_C"\n  - "sleep_for_120s"',
            updated,
        )

    def test_node_not_found_returns_error_without_modification(self):
        content = 'children:\n  - "other_node"\n'
        helper, tmpdir = self._make_helper(content)
        act = {"node": "missing_node", "param": "approach_distance", "occurrence": 1}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.set_action_pause("x")

        self.assertFalse(result["ok"])
        self.assertIn("未找到", result["error"])
        self.assertEqual(self._read_template(tmpdir), content)

    def test_lkf_robot_uses_e_lkf_template(self):
        content = 'children:\n  - "move_left_arm_to_place_cup_E"\n'
        helper, tmpdir = self._make_helper(
            content, robot="RobotE_LKF", template_name="TEMPLATE-E-LKF.yaml"
        )
        act = {"node": "move_left_arm_to_place_cup_E", "param": "approach_distance", "occurrence": 1}

        with mock.patch.object(arm_config_utils.ArmConfigHelper, "find_action", return_value=act):
            result = helper.set_action_pause("x")

        self.assertTrue(result["ok"])
        self.assertTrue(result["template"].endswith("TEMPLATE-E-LKF.yaml"))
        updated = self._read_template(tmpdir, "TEMPLATE-E-LKF.yaml")
        self.assertIn('  - "move_left_arm_to_place_cup_E"\n  - "sleep_for_120s"', updated)


if __name__ == "__main__":
    unittest.main()
