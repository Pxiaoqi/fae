#!/usr/bin/env python3
"""为 arm-true 页面提供目录浏览、模板匹配和 YAML 参数更新能力。"""

import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

ACTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arm_actions.json")

# 前端选择“本机文件（不使用 Docker）”时显式传入的哨兵值，
# 避免与“未指定容器 → 使用环境变量默认容器”的行为混淆。
LOCAL_SENTINEL = "__local__"

# PIPELINE.yaml 中 active_behavior_tree（如 RobotB/C/D/E/F）尾部字母
# 对应 arm_actions.json 的设备 key 与中文名。A 为已弃用的咖啡语音流程，仍归咖啡机。
ROBOT_LETTER_TO_DEVICE = {
    "A": "coffee",
    "B": "coffee",
    "C": "ice_cream",
    "D": "new_ice_cream",
    "E": "beer",
    "F": "cocktail",
}
ROBOT_DEVICE_LABELS = {
    "coffee": "咖啡机",
    "ice_cream": "冰激凌机",
    "new_ice_cream": "新冰激凌机",
    "beer": "啤酒机",
    "cocktail": "鸡尾酒机",
}

# 动作调参时插入行为树的 120s 暂停节点（模板中最多保留一条）
PAUSE_NODE = "sleep_for_120s"


class ArmConfigHelper:
    """统一封装 COFFEE 配置目录的读取、搜索和更新。"""

    def __init__(self, base_dir: Optional[str] = None, arm_config_path: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir or os.path.join(os.path.dirname(__file__), ".."))
        self.template_dir = self.base_dir
        self._arm_config_path_override = arm_config_path

    @staticmethod
    def list_docker_containers() -> List[str]:
        """列出本机 coffee-版本号 形式的 Docker 容器（含已停止）。"""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            # 只保留 coffee-<版本号> 形式，如 coffee-2.1.7 / coffee-v2.1.7
            pattern = re.compile(r"^coffee-v?\d+\.\d+(\.\d+)*$")
            return sorted(name for name in names if pattern.match(name))
        except Exception:
            return []

    @staticmethod
    def _load_actions_config() -> Dict[str, Any]:
        """读取 arm_actions.json：{设备: {label, stages: {阶段: [{action,node,param}]}}}"""
        if not os.path.exists(ACTIONS_FILE):
            return {}
        try:
            with open(ACTIONS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    @staticmethod
    def _iter_actions(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """遍历配置中所有动作（含推断的出现次数与 id）。"""
        out: List[Dict[str, Any]] = []
        for dev_key, dev in cfg.items():
            if not isinstance(dev, dict):
                continue
            counts: Dict[tuple, int] = {}
            for stage_label, acts in (dev.get("stages") or {}).items():
                for a in acts or []:
                    if not isinstance(a, dict):
                        continue
                    node = str(a.get("node", "") or "")
                    param = str(a.get("param", "") or "")
                    counts[(node, param)] = counts.get((node, param), 0) + 1
                    occ = counts[(node, param)]
                    out.append({
                        "id": f"{node}::{param}::{occ}",
                        "label": str(a.get("action", "") or node),
                        "node": node,
                        "param": param,
                        "occurrence": occ,
                        "device": dev_key,
                        "stage": stage_label,
                    })
        return out

    def list_actions(self, container: Optional[str] = None) -> Dict[str, Any]:
        """返回按 active_behavior_tree 过滤后的设备/阶段/动作树（供前端下拉与增删）。

        每次调用读取 PIPELINE.yaml 的 active_behavior_tree（如 RobotC），只保留
        对应机器人的动作配置；读取失败时回退为全部分组，保证工具仍可用。
        """
        cfg = ArmConfigHelper._load_actions_config()
        active = self.get_active_behavior_tree(container)
        device = active.get("device") if active.get("ok") else None
        tree: List[Dict[str, Any]] = []
        for dev_key, dev in cfg.items():
            if device is not None and dev_key != device:
                continue
            if not isinstance(dev, dict):
                continue
            stages = []
            counts: Dict[tuple, int] = {}
            for stage_label, acts in (dev.get("stages") or {}).items():
                items = []
                for a in acts or []:
                    if not isinstance(a, dict):
                        continue
                    node = str(a.get("node", "") or "")
                    param = str(a.get("param", "") or "")
                    counts[(node, param)] = counts.get((node, param), 0) + 1
                    occ = counts[(node, param)]
                    items.append({
                        "id": f"{node}::{param}::{occ}",
                        "label": str(a.get("action", "") or node),
                        "node": node,
                        "param": param,
                        "occurrence": occ,
                    })
                stages.append({"label": stage_label, "actions": items})
            tree.append({"id": dev_key, "label": str(dev.get("label", dev_key)), "stages": stages})
        filtered_cfg = {k: v for k, v in cfg.items() if device is None or k == device}
        return {"ok": True, "tree": tree, "config": filtered_cfg, "active_robot": active}

    @staticmethod
    def find_action(action_id: str) -> Optional[Dict[str, Any]]:
        """按 id（node::param::occurrence）查找动作。"""
        for act in ArmConfigHelper._iter_actions(ArmConfigHelper._load_actions_config()):
            if act["id"] == action_id:
                return act
        return None

    @staticmethod
    def save_actions(config: Any) -> Dict[str, Any]:
        """保存 arm_actions.json（设备/stages 格式）。"""
        if not isinstance(config, dict):
            return {"ok": False, "error": "配置必须是 JSON 对象"}
        try:
            with open(ACTIONS_FILE, "w", encoding="utf-8") as fh:
                json.dump(config, fh, ensure_ascii=False, indent=2)
            return {"ok": True, "path": ACTIONS_FILE}
        except Exception as exc:
            return {"ok": False, "error": f"保存动作配置失败: {exc}"}

    def _refresh_runtime_settings(self, container: Optional[str] = None) -> None:
        self.docker_container = (
            None
            if container == LOCAL_SENTINEL
            else (container or os.getenv("ARM_DOCKER_CONTAINER"))
        )
        candidate = self._arm_config_path_override or os.getenv("ARM_CONFIG_PATH") or os.getenv("ARM_YAML_PATH")
        if candidate:
            self.arm_config_path = candidate
        elif self.docker_container:
            # Docker 模式下默认使用 COFFEE 容器内的 ARM.yaml
            self.arm_config_path = "/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml"
        else:
            self.arm_config_path = os.path.abspath(os.path.join(self.base_dir, "ARM.yaml"))

    def list_directory(self, path: Optional[str] = None, container: Optional[str] = None) -> Dict[str, Any]:
        self._refresh_runtime_settings(container)
        if self.docker_container:
            target = path or self.arm_config_path or self.base_dir
            try:
                result = subprocess.run(
                    ["docker", "exec", self.docker_container, "sh", "-lc", f"ls -1a '{target}'"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except Exception as exc:
                return {"path": target, "entries": [], "error": f"docker_dir_failed: {exc}"}

            try:
                parsed = json.loads(result.stdout)
            except Exception:
                parsed = None

            if isinstance(parsed, list):
                return {"ok": True, "path": target, "entries": parsed}

            entries = []
            for line in result.stdout.splitlines():
                name = line.strip()
                if not name or name in {".", ".."}:
                    continue
                full_path = os.path.join(target, name) if not target.endswith("/") else f"{target}{name}"
                is_dir = False
                is_file = True
                try:
                    probe = subprocess.run(
                        ["docker", "exec", self.docker_container, "sh", "-lc", f"if [ -d '{full_path}' ]; then echo dir; elif [ -f '{full_path}' ]; then echo file; fi"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    if "dir" in probe.stdout:
                        is_dir = True
                        is_file = False
                except Exception:
                    pass
                entries.append({"name": name, "path": full_path, "is_dir": is_dir, "is_file": is_file})
            return {"ok": True, "path": target, "entries": entries}

        target = os.path.abspath(path or self.base_dir)
        if not self._is_within_base(target):
            target = self.base_dir
        if not os.path.exists(target):
            return {"path": target, "entries": [], "error": "path_not_found"}

        entries = []
        for entry in sorted(os.listdir(target)):
            full_path = os.path.join(target, entry)
            entries.append({
                "name": entry,
                "path": full_path,
                "is_dir": os.path.isdir(full_path),
                "is_file": os.path.isfile(full_path),
            })
        return {"path": target, "entries": entries}

    def read_text_file(self, path: str, container: Optional[str] = None) -> Dict[str, Any]:
        self._refresh_runtime_settings(container)
        if not path:
            return {"ok": False, "error": "missing_path"}

        if self.docker_container:
            try:
                result = subprocess.run(
                    ["docker", "exec", self.docker_container, "cat", path],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except Exception as exc:
                return {"ok": False, "error": f"docker_read_failed: {exc}"}
            content = result.stdout
            return {"ok": True, "path": path, "content": content, "size": len(content), "source": "docker"}

        full_path = os.path.abspath(path)
        if not self._is_within_base(full_path):
            return {"ok": False, "error": "path_outside_scope"}
        if not os.path.exists(full_path):
            return {"ok": False, "error": "file_not_found"}
        with open(full_path, "r", encoding="utf-8", newline="") as fh:
            content = fh.read()
        return {"ok": True, "path": full_path, "content": content, "size": len(content), "source": "local"}

    def write_text_file(self, path: str, content: str, container: Optional[str] = None) -> Dict[str, Any]:
        self._refresh_runtime_settings(container)
        if not path:
            return {"ok": False, "error": "missing_path"}

        if self.docker_container:
            try:
                subprocess.run(
                    ["docker", "exec", "-i", self.docker_container, "sh", "-lc", f"cat > '{path}'"],
                    input=(content or ""),
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except Exception as exc:
                return {"ok": False, "error": f"docker_write_failed: {exc}"}
            return {"ok": True, "path": path, "source": "docker"}

        full_path = os.path.abspath(path)
        if not self._is_within_base(full_path):
            return {"ok": False, "error": "path_outside_scope"}
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content or "")
        return {"ok": True, "path": full_path, "source": "local"}

    def _iter_arm_blocks(self, content: str) -> List[Dict[str, Any]]:
        lines = content.splitlines()
        blocks: List[Dict[str, Any]] = []
        line_offsets = [0]
        for line in lines:
            line_offsets.append(line_offsets[-1] + len(line) + 1)

        for idx, line in enumerate(lines):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^(\s*)([A-Za-z0-9_.:/-]+):(?:\s*(.*))?$", line)
            if not match:
                continue
            indent = len(match.group(1))
            key_name = match.group(2)
            start_idx = idx
            end_idx = len(lines)
            for next_idx in range(idx + 1, len(lines)):
                next_line = lines[next_idx]
                if not next_line.strip() or next_line.lstrip().startswith("#"):
                    continue
                next_indent = len(next_line) - len(next_line.lstrip(" "))
                if next_indent <= indent:
                    end_idx = next_idx
                    break
            start_offset = line_offsets[start_idx]
            end_offset = line_offsets[end_idx]
            block_text = "\n".join(lines[start_idx:end_idx])
            blocks.append({
                "key": key_name,
                "indent": indent,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "text": block_text,
                "line": start_idx + 1,
            })
        return blocks

    def _find_arm_block(self, content: str, key_name: str) -> Optional[Dict[str, Any]]:
        for block in self._iter_arm_blocks(content):
            if block["key"].lower() == key_name.lower():
                return block
        return None

    def _count_param_occurrences(self, block_text: str, key: str) -> int:
        """统计块内 key 出现的次数（用于跨块 occurrence 定位）。"""
        pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*:")
        return sum(1 for line in block_text.splitlines() if pattern.match(line))

    def _find_param_region(self, content: str, node: str, param: str, occurrence: int = 1):
        """定位 (node, param, occurrence)，支持同一 node 出现多个独立块的情况。

        返回 (block, region) 或 (None, None)。occurrence 从第一个匹配块开始累计：
        块内出现次数不足时继续在下一个同名块中查找。
        """
        remaining = occurrence
        for block in self._iter_arm_blocks(content):
            if block["key"].lower() != node.lower():
                continue
            count = self._count_param_occurrences(block["text"], param)
            if count >= remaining:
                region = self._extract_param_occurrence(block["text"], param, remaining)
                if region is not None:
                    return block, region
            remaining -= count
        return None, None

    def _is_within_base(self, path: str) -> bool:
        try:
            common = os.path.commonpath([self.base_dir, path])
        except ValueError:
            return False
        return common == self.base_dir

    # ---------------- ARM.yaml 内容读写（本地/Docker 统一） ----------------
    def _read_arm_yaml_content(self, container: Optional[str] = None):
        self._refresh_runtime_settings(container)
        if self.docker_container:
            try:
                result = subprocess.run(
                    ["docker", "exec", self.docker_container, "cat", self.arm_config_path],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return result.stdout, None
            except Exception as exc:
                return None, f"docker_read_failed: {exc}"
        if not os.path.exists(self.arm_config_path):
            return None, "arm_config_not_found"
        try:
            with open(self.arm_config_path, "r", encoding="utf-8") as fh:
                return fh.read(), None
        except Exception as exc:
            return None, f"read_failed: {exc}"

    def _write_arm_yaml_content(self, content: str, container: Optional[str] = None):
        self._refresh_runtime_settings(container)
        if self.docker_container:
            try:
                subprocess.run(
                    ["docker", "exec", "-i", self.docker_container, "sh", "-lc", f"cat > '{self.arm_config_path}'"],
                    input=content,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return True, None
            except Exception as exc:
                return False, f"docker_write_failed: {exc}"
        try:
            with open(self.arm_config_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            return True, None
        except Exception as exc:
            return False, f"write_failed: {exc}"

    # ---------------- active_behavior_tree 解析 ----------------
    def _read_pipeline_content(self, container: Optional[str] = None):
        """读取与 ARM.yaml 同目录的 PIPELINE.yaml。"""
        self._refresh_runtime_settings(container)
        pipeline_path = os.path.join(os.path.dirname(self.arm_config_path), "PIPELINE.yaml")
        if self.docker_container:
            try:
                result = subprocess.run(
                    ["docker", "exec", self.docker_container, "cat", pipeline_path],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return result.stdout, None
            except Exception as exc:
                return None, f"docker_read_failed: {exc}"
        if not os.path.exists(pipeline_path):
            return None, "pipeline_not_found"
        try:
            with open(pipeline_path, "r", encoding="utf-8") as fh:
                return fh.read(), None
        except Exception as exc:
            return None, f"read_failed: {exc}"

    def get_active_behavior_tree(self, container: Optional[str] = None) -> Dict[str, Any]:
        """读取 PIPELINE.yaml 的 active_behavior_tree 并映射到机器人设备。

        返回 {ok, value, robot_letter, device, label}；读取失败时 ok=False 并尽量
        保留 value/robot_letter，由调用方决定回退策略。
        """
        empty = {
            "ok": False,
            "value": None,
            "robot_letter": None,
            "device": None,
            "label": None,
        }
        content, err = self._read_pipeline_content(container)
        if err:
            return {**empty, "error": err}
        match = re.search(r"^\s*active_behavior_tree\s*:\s*([^#\n]+)", content, re.MULTILINE)
        if not match:
            return {**empty, "error": "active_behavior_tree 未找到"}
        value = match.group(1).strip().strip("\"'")
        letter_match = re.search(r"Robot([A-Z])", value)
        letter = letter_match.group(1) if letter_match else (value[-1].upper() if value else None)
        device = ROBOT_LETTER_TO_DEVICE.get(letter)
        label = ROBOT_DEVICE_LABELS.get(device)
        if device is None:
            return {
                **empty,
                "error": f"未识别的机器人标识 {value}",
                "value": value,
                "robot_letter": letter,
            }
        return {
            "ok": True,
            "value": value,
            "robot_letter": letter,
            "device": device,
            "label": label,
        }

    # ---------------- TEMPLATE-*.yaml 暂停节点管理 ----------------
    def get_template_path(self, container: Optional[str] = None) -> tuple:
        """根据 active_behavior_tree 返回对应的 TEMPLATE-*.yaml 路径。

        RobotB/C/D/E/F -> TEMPLATE-B/C/D/E/F.yaml；RobotE_LKF -> TEMPLATE-E-LKF.yaml。
        返回 (path, None) 或 (None, error)。
        """
        active = self.get_active_behavior_tree(container)
        if not active.get("ok"):
            return None, active.get("error") or "无法确定 active_behavior_tree"
        value = (active.get("value") or "").upper()
        letter = active.get("robot_letter")
        if "LKF" in value:
            filename = "TEMPLATE-E-LKF.yaml"
        elif letter:
            filename = f"TEMPLATE-{letter}.yaml"
        else:
            return None, "无法确定模板文件"
        self._refresh_runtime_settings(container)
        return os.path.join(os.path.dirname(self.arm_config_path), filename), None

    def set_action_pause(self, action_id: str, container: Optional[str] = None) -> Dict[str, Any]:
        """在动作对应机器人模板的节点后插入 120s 暂停。

        规则：先删除模板中所有已存在的 sleep_for_120s（保证只保留一条），
        再在所选节点（按 occurrence 定位）的下一行插入
        `- "sleep_for_120s"`，实现"切换其他动作后删除旧暂停"。
        """
        act = self.find_action(action_id)
        if act is None:
            return {"ok": False, "error": "action_not_found"}
        node = str(act.get("node", "") or "")
        occurrence = int(act.get("occurrence", 1) or 1)
        if not node:
            return {"ok": False, "error": "动作未配置 node"}

        template_path, err = self.get_template_path(container)
        if err:
            return {"ok": False, "error": err}

        read = self.read_text_file(template_path, container=container)
        if not read.get("ok"):
            return {"ok": False, "error": f"读取模板失败: {read.get('error')}"}

        lines = read["content"].splitlines()
        pause_re = re.compile(
            r"^\s*-\s*['\"]?" + re.escape(PAUSE_NODE) + r"['\"]?\s*(#.*)?$"
        )
        kept = [ln for ln in lines if not pause_re.match(ln)]

        node_re = re.compile(
            r"^\s*-\s*['\"]?" + re.escape(node) + r"['\"]?\s*(#.*)?$"
        )
        count = 0
        first_at = None
        insert_at = None
        for i, line in enumerate(kept):
            if node_re.match(line):
                count += 1
                if first_at is None:
                    first_at = i
                if count == occurrence:
                    insert_at = i
                    break
        # 模板中节点可能只出现一次（arm_actions.json 里同一 node 有多个 occurrence，
        # 但模板只引用一次），此时无需按 occurrence 重复查找，回退到第一处即可。
        if insert_at is None:
            insert_at = first_at
        if insert_at is None:
            return {
                "ok": False,
                "error": f"模板 {os.path.basename(template_path)} 中未找到节点 {node}",
            }

        indent_match = re.match(r"^(\s*)", kept[insert_at])
        indent = indent_match.group(1) if indent_match else ""
        new_lines = (
            kept[: insert_at + 1]
            + [f'{indent}- "{PAUSE_NODE}"']
            + kept[insert_at + 1:]
        )
        updated = "\n".join(new_lines) + "\n"

        written = self.write_text_file(template_path, updated, container=container)
        if not written.get("ok"):
            return {"ok": False, "error": f"写入模板失败: {written.get('error')}"}
        return {
            "ok": True,
            "template": template_path,
            "pause": PAUSE_NODE,
            "node": node,
            "occurrence": occurrence,
            "line": insert_at + 1,
        }

    # ---------------- approach_distance 解析与更新 ----------------
    def _extract_param_occurrence(self, block_text: str, key: str, occurrence: int = 1) -> Optional[Dict[str, Any]]:
        """定位块内 key 第 occurrence 次的参数区域。

        支持两种形态：
        - list（数组）：kind=list, value, start_line, bracket_line, bracket_prefix, end_line
        - scalar（单个数值，如 num_revolutions: 3）：kind=scalar, value, line, comment
        """
        lines = block_text.splitlines()
        pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*:")
        count = 0
        for i, line in enumerate(lines):
            if not pattern.match(line):
                continue
            count += 1
            if count != occurrence:
                continue
            indent = len(line) - len(line.lstrip())
            j = i
            start_idx = line.find("[")
            while start_idx == -1 and j + 1 < len(lines):
                nxt = lines[j + 1]
                if len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                j += 1
                start_idx = lines[j].find("[")
            if start_idx == -1:
                # 标量：param: <数字> [# 注释]
                content_after = line.split(":", 1)[1] if ":" in line else ""
                mnum = re.match(r"\s*(-?[\d.]+(?:[eE][+-]?\d+)?)", content_after)
                if mnum is None:
                    return None
                comment = line.split("#", 1)[1] if "#" in line else ""
                return {
                    "kind": "scalar",
                    "value": float(mnum.group(1)),
                    "line": i,
                    "comment": comment,
                }
            depth = 0
            region_lines: List[str] = []
            for k in range(j, len(lines)):
                text = lines[k] if k > j else lines[k][start_idx:]
                region_lines.append(text)
                for ch in text:
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            clean = []
                            for rl in region_lines:
                                rl = rl.split("#", 1)[0]
                                if rl.strip():
                                    clean.append(rl)
                            raw = "\n".join(clean)
                            # YAML 允许尾逗号，JSON 不允许，去掉 `],` 前的逗号
                            raw = re.sub(r",\s*\]", "]", raw)
                            try:
                                value = json.loads(raw)
                            except Exception:
                                return None
                            return {
                                "kind": "list",
                                "value": value,
                                "start_line": i,
                                "bracket_line": j,
                                "bracket_prefix": lines[j][:start_idx],
                                "end_line": k,
                            }
            return None
        return None

    @staticmethod
    def _normalize_rows(value: Any):
        """把解析出的数组值规整为行列表，返回 (rows, depth)。"""
        if isinstance(value, list) and value and isinstance(value[0], list):
            if value[0] and isinstance(value[0][0], list):
                return value[0], 3
            return value, 2
        return [value] if isinstance(value, list) else [], 1

    @staticmethod
    def _nest_rows(rows: List[Any], depth: int) -> Any:
        if depth == 3:
            return [rows]
        if depth == 2:
            return rows
        return rows[0] if rows else []

    @staticmethod
    def _default_value_labels(count: int) -> List[str]:
        if count == 3:
            return ["x+ 深 / x- 浅", "y+ 左 / y- 右", "z+ 上 / z- 下"]
        if count == 7:
            return ["J1", "J2", "J3", "J4", "J5", "J6", "J7"]
        return [f"V{i + 1}" for i in range(count)]

    def get_action_value(self, action_id: str, container: Optional[str] = None) -> Dict[str, Any]:
        """读取动作配置指定参数（第 occurrence 处）的当前值。"""
        act = self.find_action(action_id)
        if act is None:
            return {"ok": False, "error": "action_not_found"}
        node = act.get("node", "")
        param = act.get("param", "")
        occurrence = int(act.get("occurrence", 1) or 1)
        content, err = self._read_arm_yaml_content(container)
        if err:
            return {"ok": False, "error": err}
        block, region = self._find_param_region(content, node, param, occurrence)
        if block is None or region is None:
            return {"ok": False, "error": f"节点 {node} 参数 {param} 第 {occurrence} 处未找到"}
        if region["kind"] == "scalar":
            rows = [[region["value"]]]
            depth = 0
        else:
            rows, depth = self._normalize_rows(region["value"])
        value_count = len(rows[0]) if rows and rows[0] else 1
        return {
            "ok": True,
            "action": act,
            "line": block["line"] + region.get("start_line", region.get("line", 0)) + 1,
            "rows": rows,
            "depth": depth,
            "value_count": value_count,
            "value_labels": self._default_value_labels(value_count),
        }

    def update_action_value(self, action_id: str, rows: Any, container: Optional[str] = None) -> Dict[str, Any]:
        """定向替换动作配置指定参数（第 occurrence 处）的值。"""
        act = self.find_action(action_id)
        if act is None:
            return {"ok": False, "error": "action_not_found"}
        node = act.get("node", "")
        param = act.get("param", "")
        occurrence = int(act.get("occurrence", 1) or 1)
        content, err = self._read_arm_yaml_content(container)
        if err:
            return {"ok": False, "error": err}
        block, region = self._find_param_region(content, node, param, occurrence)
        if block is None or region is None:
            return {"ok": False, "error": f"节点 {node} 参数 {param} 第 {occurrence} 处未找到"}

        block_lines = block["text"].splitlines()
        if region["kind"] == "scalar":
            try:
                val = float(rows[0][0])
            except Exception:
                return {"ok": False, "error": "无效的数值"}
            num_str = str(int(val)) if float(val).is_integer() else repr(val)
            head = block_lines[region["line"]].split(":", 1)[0]
            comment = ("  #" + region["comment"]) if region.get("comment") else ""
            block_lines[region["line"]] = head + ": " + num_str + comment
        else:
            try:
                normalized = [[float(v) for v in row] for row in rows]
                for row in normalized:
                    if not row:
                        raise ValueError("空行")
            except Exception as exc:
                return {"ok": False, "error": f"无效的数据格式: {exc}"}
            _, depth = self._normalize_rows(region["value"])
            new_value = self._nest_rows(normalized, depth)
            new_line = region["bracket_prefix"] + json.dumps(new_value, ensure_ascii=False)
            block_lines[region["bracket_line"]:region["end_line"] + 1] = [new_line]

        new_block_text = "\n".join(block_lines)
        updated = content[:block["start_offset"]] + new_block_text + "\n" + content[block["end_offset"]:]
        ok, werr = self._write_arm_yaml_content(updated, container)
        if not ok:
            return {"ok": False, "error": werr}
        return {"ok": True, "action_id": action_id}
