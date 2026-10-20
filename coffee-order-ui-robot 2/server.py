#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智魔方点单系统 · 可视化点单服务（机器人可部署版）

两种运行模式（通过环境变量 COFFEE_DIRECT 切换）：

1) 容器内模式（推荐，机器人用）：
      COFFEE_DIRECT=1 python3 server.py
   直接在容器里运行，导入容器内已有的 coffee_order_manager_12.py，
   把订单写入 /root/AlphaBrainSystem/local/mqtt_orders.txt。
   不需要宿主机 docker CLI，不依赖任何服务。

2) 主机桥接模式（Mac 上当前用法）：
      python3 server.py            # COFFEE_DIRECT 不设置
   通过 `docker exec` 调用容器内的下单模块，适合点单服务和容器分离的情况。

其他环境变量：
  COFFEE_UI_PORT        监听端口，默认 8077
  COFFEE_CONTAINER      容器名（桥接模式用），默认 coffee-v2.1.6
  COFFEE_MANAGER_DIR    容器内下单模块目录，默认 /root/AlphaBrainSystem/tools/interfaces
  COFFEE_ORDER_FILE     订单文件路径（直写兜底模式用），默认 /root/AlphaBrainSystem/local/mqtt_orders.txt

页面：分类 tab（咖啡/冰激凌/啤酒/鸡尾酒）动态切换，数据来自容器内
  PIPELINE.yaml + INTERFACES.yaml + 外部 menu_config.yaml。
  4x2 宫格，点击饮品即下单。图片空缺，用渐变色卡片占位。
"""

import json
import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - 宿主解析交给容器内 yaml
    _yaml = None

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("COFFEE_UI_PORT", "8077"))
CONTAINER = os.environ.get("COFFEE_CONTAINER", "coffee-v2.1.6")
DOCKER = shutil.which("docker") or "/usr/local/bin/docker"
MANAGER_DIR = os.environ.get(
    "COFFEE_MANAGER_DIR", "/root/AlphaBrainSystem/tools/interfaces"
)
ORDER_FILE = os.environ.get(
    "COFFEE_ORDER_FILE", "/root/AlphaBrainSystem/local/mqtt_orders.txt"
)
ORDER_TIMES_LOG = os.environ.get("COFFEE_ORDER_TIMES_LOG", str(ROOT / "order_times.log"))
timing_config_path = os.environ.get("COFFEE_TIMING_CONFIG", str(ROOT / "timing_config.yaml"))
TIMING_SWITCH_FILE = ROOT / "timing_switch.json"
IN_CONTAINER = os.environ.get("COFFEE_DIRECT", "").strip().lower() in (
    "1", "true", "yes", "on",
)

SYSTEM_ROOT = "/root/AlphaBrainSystem"
PIPELINE_PATH = os.environ.get(
    "COFFEE_PIPELINE", SYSTEM_ROOT + "/configs/behavior/COFFEE/PIPELINE.yaml"
)
INTERFACES_PATH = os.environ.get(
    "COFFEE_INTERFACES", SYSTEM_ROOT + "/configs/behavior/COFFEE/INTERFACES.yaml"
)
MENU_CONFIG = ROOT / "menu_config.yaml"
OVERRIDES_FILE = ROOT / "menu_overrides.json"
ORDERS_LOG = os.environ.get("COFFEE_ORDERS_LOG", str(ROOT / "orders.log"))
_log_lock = threading.Lock()

ALLOWED_TYPES = {17, 18, 19, 20, 21}  # 菜单加载失败时的兜底
MAX_QTY = 10

DRINK_CN = {
    "espresso": "意式浓缩",
    "americano": "美式",
    "latte": "拿铁",
    "macchiato": "拿铁玛奇朵",
    "cappuccino": "卡布奇诺",
    "hot_milk": "热牛奶",
    "milk": "热牛奶",
    "iced_latte": "冰拿铁",
    "iced_milk": "冰牛奶",
    "iced_americano": "冰美式",
    "iced_macchiato": "冰拿铁玛奇朵",
    "hot_water": "热水",
    "water": "常温水",
    "icecream": "冰激凌",
    "beer": "啤酒",
    "beer_type_1": "百香果啤酒",
    "beer_type_2": "龙井茶啤酒",
    "beer_type_3": "浑浊 IPA",
    "cocktail": "鸡尾酒",
    "霓虹雨林": "霓虹雨林",
    "落日航线": "落日航线",
    "银翼花园": "银翼花园",
    "玫瑰星云": "玫瑰星云",
    "爱宝特调": "爱宝特调",
    "柠檬": "柠檬",
    "西瓜": "西瓜",
    "荔枝": "荔枝",
    # v2.2.5 新增品类（type 25-33）
    "pocari_sweat": "宝矿力水特",
    "potato_chips": "薯片",
    "protein_bar_green": "蛋白棒·绿",
    "protein_bar_red": "蛋白棒·红",
    "jay_blind_box": "Jay 盲盒",
    "jay_small_blind_box": "Jay 小盲盒",
    "yellow_box": "黄色盲盒",
    "blue_toy_box": "蓝色玩具盒",
    "brown_toy_box": "棕色玩具盒",
}

# 鸡尾酒分类的专属图标（type -> emoji）
COCKTAIL_ICONS = {17: "🌴", 18: "🌇", 19: "🦋", 20: "🌹", 21: "✨"}
# 鸡尾酒前五种固定配色（type -> grad-cocktail-N）
COCKTAIL_COLORS = {17: 1, 18: 2, 19: 3, 20: 4, 21: 5}

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


# ---------------------------------------------------------------- 下单实现

def _import_manager():
    """把容器内下单模块加入 sys.path 并返回模块对象。"""
    sys.path.insert(0, MANAGER_DIR)
    import coffee_order_manager_12 as manager  # noqa: PLC0415
    return manager


def _fallback_add_order(drink_type: int, quantity: int) -> dict:
    """兜底：不依赖容器内模块，直接按同一 JSON 结构写入订单文件。"""
    orders: dict = {}
    if os.path.exists(ORDER_FILE):
        try:
            with open(ORDER_FILE, "r", encoding="utf-8") as f:
                orders = json.loads(f.read() or "{}")
        except Exception:  # noqa: BLE001
            orders = {}

    codes = []
    order_ids = []
    first_ts = 0
    for _ in range(quantity):
        now = time.time()
        order_id = f"order_{int(now)}_{uuid.uuid4().hex[:8]}"
        pickup_code = f"{int(now) % 10000:04d}"
        ts_ms = int(now * 1000)
        if not first_ts:
            first_ts = ts_ms
        orders[order_id] = {
            "orderId": order_id,
            "command": "start_task",
            "isCycle": 0,
            "startTime": "",
            "endTime": "",
            "currentOrderStatus": 1,
            "taskParam": {
                "type": int(drink_type),
                "retailPickUpCode": pickup_code,
            },
            "timestamp": ts_ms,
            "received_time": now,
            "status": "pending",
        }
        codes.append(pickup_code)
        order_ids.append(order_id)

    Path(ORDER_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(ORDER_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "pickup_codes": codes,
        "order_ids": order_ids,
        "timestamp_ms": first_ts,
    }


def add_order_direct(drink_type: int, quantity: int) -> dict:
    """容器内模式：优先用系统自带下单模块，失败则直写兜底。"""
    try:
        manager = _import_manager()
        orders = manager.create_order(int(drink_type), int(quantity))
        ok = manager.add_orders_to_queue(orders)
        return {
            "ok": bool(ok),
            "pickup_codes": [
                o["taskParam"]["retailPickUpCode"] for o in orders
            ],
            "order_ids": [o["orderId"] for o in orders],
            "timestamp_ms": orders[0]["timestamp"] if orders else int(time.time() * 1000),
            "mode": "manager",
        }
    except Exception as exc:  # noqa: BLE001
        result = _fallback_add_order(int(drink_type), int(quantity))
        result["mode"] = "fallback"
        result["fallback_reason"] = str(exc)
        return result


def add_order_bridge(drink_type: int, quantity: int) -> dict:
    """主机桥接模式：docker exec 调用容器内模块。"""
    code = (
        "import sys, json;"
        f"sys.path.insert(0, {MANAGER_DIR!r});"
        "import coffee_order_manager_12 as m;"
        f"orders = m.create_order({int(drink_type)}, {int(quantity)});"
        "ok = m.add_orders_to_queue(orders);"
        "print('JSON:' + json.dumps({'ok': ok, "
        "'pickup_codes': [o['taskParam']['retailPickUpCode'] for o in orders], "
        "'order_ids': [o['orderId'] for o in orders], "
        "'timestamp_ms': orders[0]['timestamp'] if orders else 0}))"
    )
    proc = subprocess.run(
        [
            DOCKER, "exec", "-e", "PYTHONIOENCODING=utf-8",
            CONTAINER, "python3", "-c", code,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-500:] or "docker exec 失败")
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            result = json.loads(line[5:])
            result["mode"] = "bridge"
            return result
    raise RuntimeError("未解析到订单结果: " + proc.stdout[-300:])


def add_order(drink_type: int, quantity: int) -> dict:
    if IN_CONTAINER:
        return add_order_direct(int(drink_type), int(quantity))
    return add_order_bridge(int(drink_type), int(quantity))


def container_health() -> dict:
    """只读检查，不写订单。"""
    if IN_CONTAINER:
        try:
            manager = _import_manager()
            order = manager.create_order(17, 1)[0]
            return {
                "mode": "direct",
                "layout": manager.ACTIVE_LAYOUT,
                "source": manager.MENU_SOURCE,
                "pickup": order["taskParam"]["retailPickUpCode"],
            }
        except Exception as exc:  # noqa: BLE001
            return {"mode": "direct-fallback", "error": str(exc), "order_file": ORDER_FILE}

    code = (
        "import sys, json;"
        f"sys.path.insert(0, {MANAGER_DIR!r});"
        "import coffee_order_manager_12 as m;"
        "order = m.create_order(17, 1)[0];"
        "print('JSON:' + json.dumps({'mode': 'bridge', 'layout': m.ACTIVE_LAYOUT, "
        "'source': m.MENU_SOURCE, 'pickup': order['taskParam']['retailPickUpCode']}))"
    )
    proc = subprocess.run(
        [
            DOCKER, "exec", "-e", "PYTHONIOENCODING=utf-8",
            CONTAINER, "python3", "-c", code,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-500:] or "docker exec 失败")
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    raise RuntimeError("健康检查输出异常")


# ---------------------------------------------------------------- 动态菜单

BRIDGE_MENU_SCRIPT = r"""
import json, os, sys
try:
    import yaml
except Exception:
    yaml = None
root = "/root/AlphaBrainSystem"

def load(p):
    if not p or yaml is None or not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        return {"__error__": str(e)}

pipeline = load(root + "/configs/behavior/COFFEE/PIPELINE.yaml") or {}
rp_path = pipeline.get("robot_profile")
robot_profile = load(root + "/" + rp_path) if rp_path else None
interfaces = load(root + "/configs/behavior/COFFEE/INTERFACES.yaml") or {}
cerebrum = interfaces.get("cerebrum", {}) or {}
oqc = cerebrum.get("order_queue_condition", {}) or {}
task_mapping = oqc.get("task_mapping", {}) or {}
check_names = ["check_coffee_task", "check_icecream_task", "check_beer_task", "check_cocktail_task"]
check_nodes = {}
for name in check_names:
    node = cerebrum.get(name, {}) or {}
    tv = node.get("target_values") or node.get("target_value") or []
    if not isinstance(tv, list):
        tv = [tv]
    check_nodes[name] = [str(x) for x in tv if x is not None]

menu_cfg = {}
menu_err = None
try:
    raw = sys.stdin.read()
    if raw.strip():
        menu_cfg = yaml.safe_load(raw) or {}
except Exception as e:
    menu_err = str(e)

print("JSON:" + json.dumps({
    "behavior_tree_template_files": pipeline.get("behavior_tree_template_files", []) or [],
    "active_behavior_tree": pipeline.get("active_behavior_tree"),
    "robot_profile_path": rp_path,
    "robot_profile": robot_profile,
    "task_mapping": task_mapping,
    "check_nodes": check_nodes,
    "menu_cfg": menu_cfg,
    "menu_cfg_error": menu_err,
}, ensure_ascii=False))
"""


def _container_raw_data() -> dict:
    """读取容器内 PIPELINE/INTERFACES/robot_profile，并解析 menu_config.yaml。"""
    if IN_CONTAINER:
        def load_yaml(path):
            if _yaml is None or not Path(path).exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return _yaml.safe_load(f) or {}
            except Exception as exc:  # noqa: BLE001
                return {"__error__": str(exc)}

        pipeline = load_yaml(PIPELINE_PATH) or {}
        rp_path = pipeline.get("robot_profile")
        robot_profile = load_yaml(str(Path(SYSTEM_ROOT) / rp_path)) if rp_path else None
        interfaces = load_yaml(INTERFACES_PATH) or {}
        cerebrum = interfaces.get("cerebrum", {}) or {}
        oqc = cerebrum.get("order_queue_condition", {}) or {}
        task_mapping = oqc.get("task_mapping", {}) or {}
        check_names = [
            "check_coffee_task", "check_icecream_task",
            "check_beer_task", "check_cocktail_task",
        ]
        check_nodes = {}
        for name in check_names:
            node = cerebrum.get(name, {}) or {}
            tv = node.get("target_values") or node.get("target_value") or []
            if not isinstance(tv, list):
                tv = [tv]
            check_nodes[name] = [str(x) for x in tv if x is not None]
        menu_cfg = {}
        menu_err = None
        try:
            if MENU_CONFIG.exists():
                with open(MENU_CONFIG, "r", encoding="utf-8") as f:
                    menu_cfg = _yaml.safe_load(f) or {}
        except Exception as exc:  # noqa: BLE001
            menu_err = str(exc)
        return {
            "behavior_tree_template_files": pipeline.get("behavior_tree_template_files", []) or [],
            "active_behavior_tree": pipeline.get("active_behavior_tree"),
            "robot_profile_path": rp_path,
            "robot_profile": robot_profile,
            "task_mapping": task_mapping,
            "check_nodes": check_nodes,
            "menu_cfg": menu_cfg,
            "menu_cfg_error": menu_err,
        }

    # 主机桥接：容器内 python 解析 YAML，menu_config 内容从 stdin 传入
    menu_cfg_text = ""
    try:
        if MENU_CONFIG.exists():
            menu_cfg_text = MENU_CONFIG.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        menu_cfg_text = ""
    proc = subprocess.run(
        [
            DOCKER, "exec", "-i", "-e", "PYTHONIOENCODING=utf-8",
            CONTAINER, "python3", "-c", BRIDGE_MENU_SCRIPT,
        ],
        input=menu_cfg_text,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-500:] or "读取容器配置失败")
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    raise RuntimeError("解析容器配置失败: " + proc.stdout[-300:])


def _build_menu_from_raw(cfg: dict) -> dict:
    """根据 PIPELINE/INTERFACES/robot_profile + menu_config 生成点单菜单。"""
    menu_cfg = cfg.get("menu_cfg") or {}
    task_mapping: dict = {}
    for k, v in (cfg.get("task_mapping") or {}).items():
        try:
            task_mapping[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    check_nodes = cfg.get("check_nodes") or {}
    pipeline_files = {
        os.path.basename(str(f)) for f in (cfg.get("behavior_tree_template_files") or [])
    }
    bt_map = {str(k): str(v) for k, v in (menu_cfg.get("behavior_trees") or {}).items()}
    active_bt = str(cfg.get("active_behavior_tree") or "")

    rp = cfg.get("robot_profile") or {}
    robot_id = None
    if isinstance(rp, dict):
        r = rp.get("robot")
        if isinstance(r, dict):
            robot_id = r.get("id")
        robot_id = robot_id or rp.get("id")

    robot_restrict = menu_cfg.get("robots") or {}
    overrides_all = _load_overrides()
    # 点单模块强制跟随 PIPELINE.yaml 的 active_behavior_tree
    active_cat = bt_map.get(active_bt, "")

    categories = []
    for cat in menu_cfg.get("categories") or []:
        cid = str(cat.get("id") or "")
        if not cid:
            continue
        cname = str(cat.get("name") or cid)
        cicon = str(cat.get("icon") or "🍸")
        color_key = str(cat.get("color") or cid)
        layout = str(cat.get("layout") or "4x2")

        if isinstance(robot_restrict, dict) and robot_restrict:
            allowed = robot_restrict.get(robot_id)
            if allowed is not None and cid not in {str(x) for x in allowed}:
                continue

        templates = [str(t) for t in (cat.get("templates") or [])]
        present = [t for t in templates if os.path.basename(t) in pipeline_files]
        if not present:
            continue  # 模板未出现在 PIPELINE 中则不启用该分类

        targets = set(check_nodes.get(str(cat.get("check_node") or ""), []) or [])
        drinks = []
        for t, dname in sorted(task_mapping.items()):
            if dname not in targets:
                continue
            color = "grad-" + color_key
            group_name = ""
            if cid == "cocktail" and t in COCKTAIL_COLORS:
                color = "grad-cocktail-%d" % COCKTAIL_COLORS[t]
                icon = COCKTAIL_ICONS.get(t, cicon)
            else:
                icon = cicon
            # 分类内部子分组配色（如咖啡：黑咖/奶咖/清水）
            color_groups = cat.get("color_groups") or {}
            if isinstance(color_groups, dict):
                for gid, ginfo in color_groups.items():
                    gtypes = (ginfo.get("types") or []) if isinstance(ginfo, dict) else []
                    if t in gtypes:
                        color = "grad-%s-%s" % (color_key, gid)
                        group_name = (
                            ginfo.get("name", gid) if isinstance(ginfo, dict) else str(gid)
                        )
                        break
            drink_overrides = (overrides_all.get("drinks") or {})
            dset = drink_overrides.get(str(t)) or {}
            tags = dset.get("tags")
            if not isinstance(tags, list) or not tags:
                tags = []
            disabled = bool(dset.get("disabled"))
            hint = str(dset.get("hint") or "")
            drinks.append({
                "type": t,
                "name": dname,
                "chinese": DRINK_CN.get(dname, dname),
                "icon": icon,
                "alcohol": "含酒精" in tags,
                "tags": tags,
                "disabled": disabled,
                "hint": hint,
                "color": color,
                "group_name": group_name,
            })
        if not drinks:
            continue
        categories.append({
            "id": cid,
            "name": cname,
            "icon": cicon,
            "title": str(cat.get("title") or cname),
            "layout": layout,
            "active": cid == active_cat,
            "templates": present,
            "drinks": drinks,
        })

    # 应用运行时编辑覆盖（menu_overrides.json）
    overrides = overrides_all.get("categories") or {}
    for cat in categories:
        ov = overrides.get(cat["id"])
        if not isinstance(ov, dict):
            continue
        if "layout" in ov:
            cat["layout"] = str(ov.get("layout") or "4x2")
        if isinstance(ov.get("drinks"), list):
            allowed = {
                int(x) for x in ov["drinks"] if str(x).lstrip("-").isdigit()
            }
            cat["drinks"] = [d for d in cat["drinks"] if d["type"] in allowed]

    default_cat = categories[0]["id"] if categories else ""
    if active_cat not in {c["id"] for c in categories}:
        active_cat = default_cat

    return {
        "status": "ok",
        "title": "智魔方点单系统",
        "layout": "4x2",
        "active_behavior_tree": active_bt,
        "robot_profile": cfg.get("robot_profile_path"),
        "robot_id": robot_id,
        "active_category": active_cat,
        "categories": categories,
        "poll_interval_ms": 1000 if IN_CONTAINER else 3000,
        "source": "PIPELINE.yaml + INTERFACES.yaml + menu_config.yaml",
        "menu_cfg_error": cfg.get("menu_cfg_error"),
    }


_menu_cache = {"data": None}


def load_menu(force: bool = False) -> dict:
    """菜单：服务启动时从容器读取一次，之后只用本地覆盖重建，不再访问容器。"""
    if force or _menu_cache["data"] is None:
        _menu_cache["data"] = _build_menu_from_raw(_raw_data_cached())
    return _menu_cache["data"]


def allowed_types() -> set:
    """当前菜单支持的全部 type（菜单不可用时用兜底集合）。"""
    try:
        menu = load_menu()
        types = set()
        for cat in menu.get("categories", []):
            for d in cat.get("drinks", []):
                types.add(d["type"])
        if types:
            return types
    except Exception:  # noqa: BLE001
        pass
    return ALLOWED_TYPES


def drink_cn_by_type(drink_type: int) -> str:
    """从当前菜单反查饮品中文名。"""
    try:
        menu = load_menu()
        for cat in menu.get("categories", []):
            for d in cat.get("drinks", []):
                if d["type"] == drink_type:
                    return d["chinese"]
    except Exception:  # noqa: BLE001
        pass
    return DRINK_CN.get(str(drink_type), "饮品")


# ---------------------------------------------------------------- 编辑配置

def _load_overrides() -> dict:
    if not OVERRIDES_FILE.exists():
        return {}
    try:
        return json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _save_overrides(overrides: dict) -> bool:
    try:
        OVERRIDES_FILE.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _menu_cache["data"] = None  # 编辑保存后仅用本地覆盖重建菜单
        return True
    except Exception:  # noqa: BLE001
        return False


_raw_cache = {"data": None}


def _raw_data_cached() -> dict:
    """容器配置只在第一次需要时读取一次，之后永久缓存（不再动态读取）。"""
    if _raw_cache["data"] is None:
        _raw_cache["data"] = _container_raw_data()
    return _raw_cache["data"]


def editor_data() -> dict:
    """编辑器数据：全部可下单饮品 + 各分类当前绑定与布局。"""
    raw = _raw_data_cached()
    menu_cfg = raw.get("menu_cfg") or {}
    task_mapping = {}
    for k, v in (raw.get("task_mapping") or {}).items():
        try:
            task_mapping[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    all_drinks = [
        {
            "type": t,
            "name": dname,
            "chinese": DRINK_CN.get(dname, dname),
        }
        for t, dname in sorted(task_mapping.items())
    ]
    menu = load_menu(force=True)
    overrides = _load_overrides()
    overrides_cats = overrides.get("categories") or {}
    drink_overrides = overrides.get("drinks") or {}
    # 饮品 -> 品类图标（对应饮品类型，例：鸡尾酒分类用 🍸）
    icon_by_type = {}
    for cat in menu.get("categories", []):
        cicon = cat.get("icon", "🍸")
        for d in cat.get("drinks", []):
            icon_by_type.setdefault(d["type"], cicon)
    categories = []
    for cat in menu.get("categories", []):
        ov = overrides_cats.get(cat["id"]) or {}
        categories.append({
            "id": cat["id"],
            "name": cat["name"],
            "icon": cat["icon"],
            "layout": ov.get("layout", cat.get("layout", "4x2")),
            "bound_types": [d["type"] for d in cat["drinks"]],
        })
    for drink in all_drinks:
        drink["icon"] = icon_by_type.get(drink["type"], "")  # 未被任何分类选中 -> 无图标
        dset = drink_overrides.get(str(drink["type"])) or {}
        tags = dset.get("tags")
        if not isinstance(tags, list) or not tags:
            tags = []
        drink["tags"] = tags
        drink["alcohol"] = "含酒精" in tags
        drink["disabled"] = bool(dset.get("disabled"))
        drink["hint"] = str(dset.get("hint") or "")
    return {
        "status": "ok",
        "all_drinks": all_drinks,
        "categories": categories,
        "overrides": overrides,
        "active_category": menu.get("active_category"),
        "robot_id": menu.get("robot_id"),
    }


def save_editor_changes(payload: dict) -> dict:
    """保存分类布局与饮品绑定到 menu_overrides.json。"""
    raw = _raw_data_cached()
    task_types = set()
    for k in (raw.get("task_mapping") or {}).keys():
        try:
            task_types.add(int(k))
        except (TypeError, ValueError):
            continue
    menu = load_menu(force=True)
    known = {c["id"] for c in menu.get("categories", [])}
    new_cats = payload.get("categories")
    current = _load_overrides()
    if new_cats is not None:
        if not isinstance(new_cats, dict):
            return {"ok": False, "error": "参数格式错误"}
        normalized = {}
        for cid, ov in new_cats.items():
            cid = str(cid)
            if cid not in known:
                return {"ok": False, "error": f"未知模块: {cid}"}
            if not isinstance(ov, dict):
                return {"ok": False, "error": f"模块 {cid} 配置格式错误"}
            layout = str(ov.get("layout") or "4x2")
            if layout not in ("4x2", "6x2"):
                return {"ok": False, "error": f"模块 {cid} 布局无效: {layout}"}
            drinks = ov.get("drinks")
            if not isinstance(drinks, list):
                return {"ok": False, "error": f"模块 {cid} 饮品列表格式错误"}
            types = []
            for x in drinks:
                try:
                    t = int(x)
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"模块 {cid} 含无效 type: {x}"}
                if t not in task_types:
                    return {"ok": False, "error": f"type {t} 不在可用饮品列表中"}
                types.append(t)
            normalized[cid] = {"layout": layout, "drinks": sorted(set(types))}
        # 合并而非覆盖：只更新本次编辑的分类，保留其他分类的已保存修改
        merged = current.get("categories") or {}
        merged.update(normalized)
        current["categories"] = merged
    new_drinks = payload.get("drinks")
    if new_drinks is not None:
        if not isinstance(new_drinks, dict):
            return {"ok": False, "error": "饮品设置格式错误"}
        normalized_drinks = {}
        for k, v in new_drinks.items():
            try:
                t = int(k)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"type 无效: {k}"}
            if t not in task_types:
                return {"ok": False, "error": f"type {t} 不在可用饮品列表中"}
            if not isinstance(v, dict):
                return {"ok": False, "error": f"饮品 {t} 设置格式错误"}
            tags = [str(x).strip() for x in (v.get("tags") or []) if str(x).strip()]
            normalized_drinks[str(t)] = {
                "tags": tags,
                "disabled": bool(v.get("disabled")),
                "hint": str(v.get("hint") or "").strip(),
            }
        drinks_map = current.get("drinks") or {}
        drinks_map.update(normalized_drinks)  # 只更新本次编辑的饮品
        current["drinks"] = drinks_map
    if not _save_overrides(current):
        return {"ok": False, "error": "配置写入失败"}
    return {"ok": True, "overrides_file": str(OVERRIDES_FILE)}


# ---------------------------------------------------------------- 订单日志

def write_order_log(entry: dict) -> None:
    """追加一条订单日志（JSON Lines，UTF-8）。"""
    try:
        line = json.dumps(entry, ensure_ascii=False)
        with _log_lock:
            with open(ORDERS_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def read_order_log(limit: int = 30) -> list:
    """读取订单日志，返回最新的 limit 条（新在前）。"""
    entries = []
    if not Path(ORDERS_LOG).exists():
        return entries
    try:
        with open(ORDERS_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        return []
    return entries[-limit:][::-1]


def today_orders() -> dict:
    """今日订单列表：每笔单独展示（已删除/清除的不计入），并关联制作时长。"""
    entries = read_order_log(100000)
    date_key = datetime.now().strftime("%Y-%m-%d")
    removed = {
        oid
        for e in entries if e.get("result") in ("deleted", "cleared")
        for oid in (e.get("order_ids") or [])
    }
    times_map = {}
    for te in read_order_times(100000):
        if te.get("order_id"):
            times_map[te["order_id"]] = te
    orders = []
    for entry in entries:
        if entry.get("result") != "success":
            continue
        oid = (entry.get("order_ids") or [None])[0]
        if oid and oid in removed:
            continue  # 已被删除/清除，不计入今日统计
        ts = entry.get("timestamp_ms") or 0
        if not ts:
            continue
        day = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        if day != date_key:
            continue
        t = entry.get("type")
        name = entry.get("name") or drink_cn_by_type(t) or "未知饮品"
        te = times_map.get(oid)
        orders.append({
            "order_id": oid,
            "type": t,
            "name": name,
            "placed_ms": ts,
            "duration_sec": te.get("duration_sec") if te else None,
            "timing_result": te.get("result") if te else None,
        })
    orders.sort(key=lambda x: x["placed_ms"], reverse=True)
    return {
        "status": "ok",
        "date": date_key,
        "total": len(orders),
        "orders": orders,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- 制作时长监听（cerebrum.log）

_TIMING_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})"
    r".*?event=(?P<event>\S+)"
    r".*?order=(?P<order>order_\d+_[0-9a-f]+)"
    r"(?:\s+task=(?P<task>\S+))?"
    r"(?:\s+status=(?P<status>\S+))?"
)
_TIMING_NODE_RE = re.compile(r"\snode_name=(\S+)")
_TIMING_COMP_RE = re.compile(r"\[([^\]]+)\] event=")

_timing_cfg = None
_timing_state = {}
_seen_times = set()
_timing_offsets = {}
_timing_lock = threading.Lock()
_STRUCTURAL_KEYS = {
    "name", "behavior_type", "children", "decorators", "config_ref",
    "parameters", "runtime_order_phase", "retry_behavior",
}
_resolved_chains = {}  # node_name -> [ [父层级...], ... ]


def _load_timing_config() -> dict:
    defaults = {
        "enabled": True,
        "log_glob": "/root/AlphaBrainSystem/logger/*/*/cerebrum/cerebrum.log",
        "backfill_days": 2,
        "start": {
            "event": "MOTION_COMMAND_SENT",
            "template": "",
            "path": [],
            "node_name": "move_torso_to_cup_popper_default_F",
            "after_event": "ORDER_SELECTED",
        },
        "end": {
            "event": "MOTION_COMMAND_SENT",
            "template": "",
            "path": [],
            "node_name": "move_left_gripper_to_open",
        },
        "template_dir": "/root/AlphaBrainSystem/configs/behavior/COFFEE",
        "closed_orders_file": "/root/AlphaBrainSystem/local/mqtt_closed_orders.txt",
        "active_orders_file": "/root/AlphaBrainSystem/local/mqtt_orders.txt",
        "failed_statuses": ["failed", "cancelled", "auto_cancelled", "cancel"],
        "max_duration_sec": 3600,
        "poll_sec": 2,
    }
    if _yaml is not None and Path(timing_config_path).exists():
        try:
            with open(timing_config_path, "r", encoding="utf-8") as f:
                cfg = _yaml.safe_load(f) or {}
            for k, v in cfg.items():
                defaults[k] = v
        except Exception:  # noqa: BLE001
            pass
    return defaults


def _timing_node_match(side_cfg: dict, node: str, component: str) -> bool:
    """节点匹配：
    path 可动态增删（精确段、按顺序）；path 为空时自动用 TEMPLATE 解析层级
    node_name 前缀匹配（兼容编号后缀，如 _1/_2）
    """
    node_name = str(side_cfg.get("node_name") or "")
    if node_name and not node.startswith(node_name):
        return False
    comp_segs = [s for s in component.split("/") if s]
    path = side_cfg.get("path")
    if isinstance(path, list) and path:
        return _timing_chain_in([str(p) for p in path], comp_segs)
    subtree = str(side_cfg.get("subtree") or "").strip()  # 兼容旧字段（精确段）
    if subtree:
        return _timing_chain_in([subtree], comp_segs)
    chains = _resolved_chains.get(node_name, []) if node_name else []
    if not chains:
        return True
    return any(_timing_chain_in(chain, comp_segs) for chain in chains)


def _timing_chain_in(chain, comp_segs) -> bool:
    idx = 0
    for seg in chain:
        seg = str(seg)
        if not seg:
            continue
        found = False
        while idx < len(comp_segs):
            if comp_segs[idx] == seg:
                found = True
                idx += 1
                break
            idx += 1
        if not found:
            return False
    return True


def _walk_template(node, chain, out) -> None:
    """递归行为树模板：字符串叶子记录其父级链（跳过结构性 key）。"""
    if isinstance(node, str):
        out.setdefault(node, []).append(list(chain))
    elif isinstance(node, list):
        for x in node:
            _walk_template(x, chain, out)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k in _STRUCTURAL_KEYS:
                _walk_template(v, chain, out)
            else:
                _walk_template(v, chain + [str(k)], out)


def _timing_resolve_all() -> None:
    """从 TEMPLATE-*.yaml 自动解析节点嵌套位置（用户无需手填层级）。"""
    global _resolved_chains
    _resolved_chains = {}
    if _yaml is None:
        return
    template_dir = str(_timing_cfg.get("template_dir") or "")
    for fp in sorted(glob.glob(os.path.join(template_dir, "TEMPLATE-*.yaml"))):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f) or {}
        except Exception:  # noqa: BLE001
            continue
        tmpl = data.get("behavior_tree_template") or {}
        _walk_template(tmpl, [], _resolved_chains)


def _timing_finalize(order_id: str, st: dict) -> None:
    if order_id in _seen_times:
        _timing_state.pop(order_id, None)
        return
    dur = (st["end_ms"] - st["start_ms"]) / 1000.0 if st.get("end_ms") is not None else None
    entry = {
        "order_id": order_id,
        "task": st.get("task", ""),
        "name": DRINK_CN.get(st.get("task", ""), st.get("task", "未知饮品")),
        "start_ms": st["start_ms"],
        "end_ms": st["end_ms"],
        "duration_sec": round(dur, 3) if dur is not None else None,
        "start_node": st.get("start_node", ""),
        "end_node": st.get("end_node", "move_left_gripper_to_open"),
        "result": "failed" if st.get("failed") else "success",
        "fail_reason": st.get("fail_reason"),
        "source": st.get("source", "cerebrum"),
        "time": datetime.now().isoformat(timespec="seconds"),
        "suspicious": dur is not None and dur > float(_timing_cfg.get("max_duration_sec", 3600)),
    }
    try:
        with _timing_lock:
            with open(ORDER_TIMES_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    _seen_times.add(order_id)
    _timing_state.pop(order_id, None)


def _timing_handle_line(line: str) -> None:
    m = _TIMING_LINE_RE.search(line)
    if not m:
        return
    try:
        ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return
    ts_ms = int(ts.timestamp() * 1000)
    oid = m.group("order")
    event = m.group("event")
    nm = _TIMING_NODE_RE.search(line)
    node = nm.group(1) if nm else ""
    cm = _TIMING_COMP_RE.search(line)
    component = cm.group(1) if cm else ""
    task = m.group("task") or ""
    status = m.group("status") or ""
    st = _timing_state.setdefault(oid, {
        "start_ms": None, "end_ms": None, "selected": False,
        "last_open_ms": None,
        "task": "", "start_node": "", "end_node": "move_left_gripper_to_open",
        "failed": False, "fail_reason": None, "source": "cerebrum",
    })
    if event == _timing_cfg["start"]["after_event"] and task:
        st["task"] = task
    cfg = _timing_cfg
    if event == cfg["start"]["after_event"]:
        st["selected"] = True
    if (st["selected"] and st["start_ms"] is None
            and event == cfg["start"]["event"]
            and _timing_node_match(cfg["start"], node, component)):
        st["start_ms"] = ts_ms
        st["start_node"] = node
    if event == cfg["end"]["event"] and _timing_node_match(cfg["end"], node, component):
        if st["end_ms"] is None:
            st["end_ms"] = ts_ms
            st["end_node"] = node
        st["last_open_ms"] = ts_ms
    if event == "ORDER_FINISHED":
        if st["start_ms"] is not None and st["end_ms"] is None:
            if st["last_open_ms"] is not None:
                st["end_ms"] = st["last_open_ms"]  # 无送餐转身时兜底取最后张开夹爪
            else:
                st["end_ms"] = ts_ms
            if status != "success" or "order_status=failed" in line or "order_status=cancelled" in line:
                st["failed"] = True
                st["fail_reason"] = "order_finished_" + (status or "failure")
    if st["start_ms"] is not None and st["end_ms"] is not None:
        _timing_finalize(oid, st)


def _read_json_file(path: str) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read() or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _timing_resolve_disappeared() -> None:
    """未正常闭环且订单消失 -> 判定制作失败：
    1) 关闭订单文件出现 failed/cancelled -> 失败
    2) 订单从活动队列消失且未闭环、也不在关闭文件 -> 失败
    """
    cfg = _timing_cfg
    closed = _read_json_file(cfg.get("closed_orders_file", ""))
    active = _read_json_file(cfg.get("active_orders_file", ""))
    failed_set = {str(s).lower() for s in cfg.get("failed_statuses", [])}
    for oid, st in list(_timing_state.items()):
        if st.get("start_ms") is None or st.get("end_ms") is not None:
            continue
        if oid in _seen_times:
            continue
        co = closed.get(oid)
        if isinstance(co, dict):
            status = str(co.get("status", "")).lower()
            end_ms = co.get("actualEndTime") or co.get("closedAt")
            if status in ("completed", "done", "success"):
                st["end_ms"] = end_ms or st.get("last_open_ms") or st["start_ms"]
                st["end_node"] = "closed_orders(completed)"
                st["source"] = "closed_orders"
                _timing_finalize(oid, st)
                continue
            if status in failed_set:
                st["end_ms"] = end_ms or st.get("last_open_ms") or st["start_ms"]
                st["end_node"] = "closed_orders(" + status + ")"
                st["failed"] = True
                st["fail_reason"] = "closed_status_" + status
                st["source"] = "closed_orders"
                _timing_finalize(oid, st)
                continue
        # 订单不在活动队列、也不在关闭订单：视为制作失败
        if oid not in active and oid not in closed:
            st["end_node"] = "order_disappeared"
            st["failed"] = True
            st["fail_reason"] = "order_disappeared_no_closure"
            st["source"] = "queue_disappear"
            _timing_finalize(oid, st)


def _timing_scan_file(path: str, collect: bool = True) -> None:
    try:
        size = os.path.getsize(path)
        off = _timing_offsets.get(path, 0)
        if size < off:
            off = 0  # 文件被重写，从头读
        with open(path, "r", encoding="utf-8") as f:
            f.seek(off)
            while True:
                line = f.readline()
                if not line:
                    break
                if collect:
                    _timing_handle_line(line)
            _timing_offsets[path] = f.tell()
    except Exception:  # noqa: BLE001
        pass


def _timing_backfill() -> None:
    """启动时回补最近 N 天日志（只读，offset 推进到当前末尾）。"""
    days = int(_timing_cfg.get("backfill_days", 0) or 0)
    if days <= 0:
        return
    cutoff = time.time() - days * 86400
    for path in glob.glob(_timing_cfg["log_glob"]):
        parts = path.split("/")
        try:
            idx = parts.index("logger")
            day = datetime.strptime(parts[idx + 1], "%Y-%m-%d").timestamp()
        except Exception:  # noqa: BLE001
            continue
        if day >= cutoff:
            _timing_scan_file(path)


def _timing_seed_seen() -> None:
    """启动时载入已有 order_times.log 的订单号，避免回补重复写入。"""
    for entry in read_order_times(100000):
        oid = entry.get("order_id")
        if oid:
            _seen_times.add(oid)


def _timing_observer_loop() -> None:
    _timing_reload_config()
    _timing_seed_seen()
    if _timing_cfg.get("enabled", True):
        _timing_backfill()
    while True:
        try:
            collect = _timing_switch_enabled()
            for path in glob.glob(_timing_cfg["log_glob"]):
                _timing_scan_file(path, collect=collect)
            if collect:
                _timing_resolve_disappeared()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(max(1.0, float(_timing_cfg.get("poll_sec", 2))))


def _timing_reload_config() -> None:
    """(重新)加载 timing_config.yaml，并自动解析节点嵌套位置。"""
    global _timing_cfg
    _timing_cfg = _load_timing_config()
    _timing_resolve_all()


def timing_config_get() -> dict:
    cfg = _timing_cfg or _load_timing_config()
    def side_view(side_cfg):
        node_name = str(side_cfg.get("node_name") or "")
        manual = side_cfg.get("path") or []
        chains = _resolved_chains.get(node_name, [])
        resolved = manual if manual else (chains[0] if chains else [])
        return dict(side_cfg, resolved_path=resolved)
    start = side_view(cfg["start"])
    end = side_view(cfg["end"])
    return {
        "status": "ok",
        "allowed": IN_CONTAINER,
        "start": start,
        "end": end,
        "closed_orders_file": cfg.get("closed_orders_file", ""),
        "active_orders_file": cfg.get("active_orders_file", ""),
    }


def timing_config_update(payload: dict) -> dict:
    """在线修正起止节点（template/path[]/node_name，path 可动态增删，仅容器内）。"""
    if not IN_CONTAINER:
        return {"ok": False, "error": "制作时长配置仅在程序导入容器内运行时可修改"}
    if _yaml is None:
        return {"ok": False, "error": "容器内缺少 yaml 模块，无法写配置"}
    cfg = _load_timing_config()
    changed = False
    for side in ("start", "end"):
        side_cfg = payload.get(side)
        if not isinstance(side_cfg, dict):
            continue
        node_name = str(side_cfg.get("node_name") or "").strip()
        if not node_name:
            continue
        cfg[side]["node_name"] = node_name
        cfg[side]["template"] = str(side_cfg.get("template") or "").strip()
        path = side_cfg.get("path")
        if isinstance(path, list):
            cfg[side]["path"] = [str(p).strip() for p in path if str(p).strip()]
        elif isinstance(path, str) and path.strip():
            cfg[side]["path"] = [p.strip() for p in path.split(",") if p.strip()]
        else:
            subtree = str(side_cfg.get("subtree") or "").strip()  # 兼容旧字段
            cfg[side]["path"] = [subtree] if subtree else []
        changed = True
    if not changed:
        return {"ok": False, "error": "没有可更新的参数（至少填写 node_name）"}
    try:
        with open(timing_config_path, "w", encoding="utf-8") as f:
            _yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "配置写入失败: %s" % exc}
    _timing_reload_config()
    return {"ok": True, "start": cfg["start"], "end": cfg["end"]}


def read_order_times(limit: int = 20) -> list:
    entries = []
    if not Path(ORDER_TIMES_LOG).exists():
        return entries
    try:
        with open(ORDER_TIMES_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        return []
    return entries[-limit:][::-1]


def _timing_switch_enabled() -> bool:
    """制作时长开关：仅容器内（直写模式）允许开启，默认开启。"""
    if not IN_CONTAINER:
        return False
    try:
        if TIMING_SWITCH_FILE.exists():
            data = json.loads(TIMING_SWITCH_FILE.read_text(encoding="utf-8"))
            return bool(data.get("enabled", True))
    except Exception:  # noqa: BLE001
        pass
    return True


def _set_timing_switch(enabled: bool) -> dict:
    if enabled and not IN_CONTAINER:
        return {"ok": False, "error": "制作时长监听仅在程序导入容器内运行时可开启"}
    try:
        TIMING_SWITCH_FILE.write_text(
            json.dumps({"enabled": bool(enabled)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "enabled": bool(enabled)}


_queue_cache = {"ts": 0.0, "data": {}}
QUEUE_POLL_SEC = 1.0 if IN_CONTAINER else 2.0  # 直写模式 1 秒刷新订单状态
FINISHED_STATUSES = {"done", "success", "completed", "finished"}
_order_status_cache = {}   # orderId -> {status, name, pickup, placed_ms, completed_logged}
_removed_order_ids = set()  # 已删除/清除的订单（内存缓存）
_removed_seeded = False


def _read_orders_file() -> dict:
    """直接读取订单文件（不走缓存）。"""
    if not Path(ORDER_FILE).exists():
        return {}
    try:
        with open(ORDER_FILE, "r", encoding="utf-8") as f:
            return json.loads(f.read() or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _write_orders_file(orders: dict) -> bool:
    try:
        Path(ORDER_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(ORDER_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def _docker_exec_json(code: str, timeout: int = 60) -> dict:
    """在容器里执行一段返回 JSON: 前缀的 python 代码。"""
    proc = subprocess.run(
        [
            DOCKER, "exec", "-e", "PYTHONIOENCODING=utf-8",
            CONTAINER, "python3", "-c", code,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-500:] or "docker exec 失败")
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    raise RuntimeError("解析失败: " + proc.stdout[-300:])


def _queue_orders_cached(force: bool = False) -> dict:
    """当前队列完整订单 dict（orderId -> order），直写 1 秒 / 桥接 2 秒缓存。"""
    now = time.time()
    if not force and _queue_cache["data"] and (now - _queue_cache["ts"]) < QUEUE_POLL_SEC:
        return _queue_cache["data"]
    if IN_CONTAINER:
        data = _read_orders_file()
    else:
        code = (
            "import json, os;"
            "p = %s;"
            "d = json.load(open(p)) if os.path.exists(p) else {};"
            "print('JSON:' + json.dumps(d))"
        ) % json.dumps(ORDER_FILE)
        try:
            data = _docker_exec_json(code, timeout=30)
        except Exception:  # noqa: BLE001
            data = {}
    _queue_cache["ts"] = now
    _queue_cache["data"] = data
    return data


def current_queue_status() -> dict:
    """当前队列 orderId -> status。"""
    orders = _queue_orders_cached()
    return {
        str(k): (v.get("status") if isinstance(v, dict) else None)
        for k, v in orders.items()
    }


def delete_order(order_id: str) -> dict:
    """删除单个未制作订单（status 为空或 pending）。"""
    order_id = str(order_id)
    if not IN_CONTAINER:
        code = (
            "import json, os;"
            "p = %s;"
            "oid = %s;"
            "d = json.load(open(p)) if os.path.exists(p) else {};"
            "info = d.get(oid);"
            "if info is None: print('JSON:' + json.dumps({'ok': False, 'error': 'not_found'}));"
            "elif info.get('status') not in (None, 'pending'): print('JSON:' + json.dumps({'ok': False, 'error': 'not_pending'}));"
            "else:"
            "    tp = info.get('taskParam', {}) or {};"
            "    del d[oid];"
            "    json.dump(d, open(p, 'w'), ensure_ascii=False, indent=2);"
            "    print('JSON:' + json.dumps({'ok': True, 'order_id': oid, "
            "'type': tp.get('type'), 'pickup_code': tp.get('retailPickUpCode')}))"
        ) % (json.dumps(ORDER_FILE), json.dumps(order_id))
        result = _docker_exec_json(code, timeout=60)
    else:
        orders = _read_orders_file()
        info = orders.get(order_id)
        if info is None:
            result = {"ok": False, "error": "not_found"}
        elif info.get("status") not in (None, "pending"):
            result = {"ok": False, "error": "not_pending"}
        else:
            tp = info.get("taskParam", {}) or {}
            del orders[order_id]
            _write_orders_file(orders)
            result = {
                "ok": True,
                "order_id": order_id,
                "type": tp.get("type"),
                "pickup_code": tp.get("retailPickUpCode"),
            }
    if result.get("ok"):
        _queue_cache["ts"] = 0.0
        _removed_order_ids.add(order_id)
        _order_status_cache.pop(order_id, None)
        try:
            tp = result.get("type")
            write_order_log({
                "time": datetime.now().isoformat(timespec="seconds"),
                "timestamp_ms": int(time.time() * 1000),
                "result": "deleted",
                "name": drink_cn_by_type(tp) if isinstance(tp, int) else DRINK_CN.get(str(tp), str(tp)),
                "type": tp,
                "quantity": 1,
                "pickup_codes": [result.get("pickup_code")] if result.get("pickup_code") else [],
                "order_ids": [order_id],
                "client": "local",
                "mode": "direct" if IN_CONTAINER else "bridge",
            })
        except Exception:  # noqa: BLE001
            pass
    return result


def clear_pending_orders() -> dict:
    """一键清除所有未制作订单。"""
    if not IN_CONTAINER:
        code = (
            "import json, os;"
            "p = %s;"
            "d = json.load(open(p)) if os.path.exists(p) else {};"
            "removed = [oid for oid, o in d.items() "
            "if isinstance(o, dict) and o.get('status') in (None, 'pending')];"
            "for oid in removed: del d[oid];"
            "json.dump(d, open(p, 'w'), ensure_ascii=False, indent=2);"
            "print('JSON:' + json.dumps({'ok': True, 'cleared': len(removed), 'order_ids': removed}))"
        ) % json.dumps(ORDER_FILE)
        result = _docker_exec_json(code, timeout=60)
    else:
        orders = _read_orders_file()
        removed = [
            oid for oid, o in orders.items()
            if isinstance(o, dict) and o.get("status") in (None, "pending")
        ]
        for oid in removed:
            del orders[oid]
        _write_orders_file(orders)
        result = {"ok": True, "cleared": len(removed), "order_ids": removed}
    if result.get("ok"):
        _queue_cache["ts"] = 0.0
        _removed_order_ids.update(result.get("order_ids", []))
        for oid in result.get("order_ids", []):
            _order_status_cache.pop(str(oid), None)
        try:
            write_order_log({
                "time": datetime.now().isoformat(timespec="seconds"),
                "timestamp_ms": int(time.time() * 1000),
                "result": "cleared",
                "name": "批量清除",
                "type": None,
                "quantity": result.get("cleared", 0),
                "pickup_codes": [],
                "order_ids": result.get("order_ids", []),
                "client": "local",
                "mode": "direct" if IN_CONTAINER else "bridge",
            })
        except Exception:  # noqa: BLE001
            pass
    return result


def _sweep_order_events() -> None:
    """订单状态缓存 + 完成事件记录：
    对比内存缓存与当前队列，订单从未制作变为完成/出队时，
    向订单日志追加一条 result=completed 记录（每个订单仅一次）。
    """
    global _removed_seeded
    try:
        if not _removed_seeded:
            for entry in read_order_log(5000):
                if entry.get("result") in ("deleted", "cleared"):
                    _removed_order_ids.update(entry.get("order_ids") or [])
            _removed_seeded = True

        orders = _queue_orders_cached()
        qmap = current_queue_status()
        # 当前在队列中的订单 -> 更新/加入缓存
        for oid, o in orders.items():
            if not isinstance(o, dict):
                continue
            tp = o.get("taskParam", {}) or {}
            t = tp.get("type")
            name = drink_cn_by_type(t) if isinstance(t, int) else DRINK_CN.get(str(t), str(t))
            _order_status_cache.setdefault(str(oid), {
                "status": o.get("status"),
                "name": name,
                "pickup": tp.get("retailPickUpCode", ""),
                "placed_ms": o.get("timestamp") or 0,
                "completed_logged": False,
            })

        for oid, rec in list(_order_status_cache.items()):
            if rec.get("completed_logged"):
                continue
            if str(oid) in _removed_order_ids:
                _order_status_cache.pop(oid, None)  # 被删除/清除，不再跟踪
                continue
            cur = qmap.get(str(oid))
            if cur in FINISHED_STATUSES or (cur is None and str(oid) not in orders):
                write_order_log({
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "timestamp_ms": rec.get("placed_ms") or int(time.time() * 1000),
                    "result": "completed",
                    "name": rec.get("name", "未知饮品"),
                    "type": None,
                    "quantity": 1,
                    "pickup_codes": [rec.get("pickup", "")] if rec.get("pickup") else [],
                    "order_ids": [oid],
                    "client": "system",
                    "mode": "direct" if IN_CONTAINER else "bridge",
                })
                rec["completed_logged"] = True
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- HTTP 服务

class Handler(BaseHTTPRequestHandler):
    server_version = "CoffeeOrderUI/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, path):
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        entry = STATIC_FILES.get(path)
        if entry is None:
            self._send_json(404, {"error": "not found"})
            return
        fname, ctype = entry
        try:
            data = (ROOT / fname).read_bytes()
        except OSError:
            self._send_json(404, {"error": "文件缺失: " + fname})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/editor":
            try:
                self._send_json(200, editor_data())
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
            return
        if path == "/api/orders/recent":
            try:
                _sweep_order_events()
                limit = int(parse_qs(urlparse(self.path).query).get("limit", ["3"])[0])
            except (TypeError, ValueError):
                limit = 3
            limit = max(1, min(limit, 100))
            try:
                # 只展示"制作完成"的订单：队列状态为完成，或已出队且未被删除/清除
                entries = read_order_log(500)
                qmap = current_queue_status()
                removed = {
                    oid
                    for e in entries if e.get("result") in ("deleted", "cleared")
                    for oid in (e.get("order_ids") or [])
                }
                done = []
                for entry in entries:
                    if entry.get("result") != "success":
                        continue
                    oid = (entry.get("order_ids") or [None])[0]
                    status = qmap.get(str(oid)) if oid else None
                    if status in FINISHED_STATUSES:
                        entry["queue_status"] = status
                        done.append(entry)
                    elif status is None and oid and oid not in removed:
                        entry["queue_status"] = None
                        done.append(entry)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
                return
            self._send_json(200, {
                "status": "ok",
                "total": len(done),
                "orders": done[:limit],
                "log_file": ORDERS_LOG,
            })
            return
        if path == "/api/orders/pending":
            try:
                _sweep_order_events()
                orders = _queue_orders_cached()
                pending = []
                for oid, o in orders.items():
                    if not isinstance(o, dict):
                        continue
                    # 活动队列：待制作 + 制作中（executing/processing/making）
                    if o.get("status") not in (None, "pending", "executing", "processing", "making"):
                        continue
                    tp = o.get("taskParam", {}) or {}
                    t = tp.get("type")
                    pending.append({
                        "order_id": str(oid),
                        "type": t,
                        "name": drink_cn_by_type(t) if isinstance(t, int)
                                else DRINK_CN.get(str(t), str(t)),
                        "pickup_code": tp.get("retailPickUpCode", ""),
                        "timestamp": o.get("timestamp", 0),
                        "status": o.get("status", "pending"),
                    })
                pending.sort(key=lambda x: x["timestamp"])
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
                return
            self._send_json(200, {"status": "ok", "total": len(pending), "orders": pending})
            return
        if path == "/api/orders/today":
            try:
                payload = today_orders()
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
                return
            self._send_json(200, payload)
            return
        if path == "/api/orders/times":
            try:
                limit = int(parse_qs(urlparse(self.path).query).get("limit", ["20"])[0])
            except (TypeError, ValueError):
                limit = 20
            limit = max(1, min(limit, 100))
            try:
                entries = read_order_times(limit)
                avg_entries = read_order_times(100)
                valid = [
                    e for e in entries
                    if not e.get("suspicious") and e.get("result", "success") == "success"
                ]
                avg_valid = [
                    e for e in avg_entries
                    if not e.get("suspicious") and e.get("result", "success") == "success"
                ]
                avg = (
                    round(sum(e["duration_sec"] for e in avg_valid) / len(avg_valid), 1)
                    if avg_valid else None
                )
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
                return
            self._send_json(200, {
                "status": "ok",
                "total": len(entries),
                "orders": entries,
                "avg_sec": avg,
            })
            return
        if path == "/api/timing/status":
            self._send_json(200, {
                "status": "ok",
                "enabled": _timing_switch_enabled(),
                "allowed": IN_CONTAINER,  # 仅容器内可开启
                "mode": "direct" if IN_CONTAINER else "bridge",
            })
            return
        if path == "/api/timing/config":
            try:
                payload = timing_config_get()
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
                return
            self._send_json(200, payload)
            return
        if path == "/api/menu":
            try:
                payload = load_menu()
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "error": str(exc)})
                return
            self._send_json(200, payload)
            return
        if path == "/api/health":
            payload = {
                "status": "ok",
                "service": "智魔方点单系统",
                "drinks": {str(k): v for k, v in DRINK_CN.items()},
                "mode": "direct" if IN_CONTAINER else "bridge",
                "container": CONTAINER,
                "docker_ok": False,
            }
            try:
                payload["container_info"] = container_health()
                payload["docker_ok"] = True
            except Exception as exc:  # noqa: BLE001
                payload["docker_error"] = str(exc)
            self._send_json(200, payload)
            return
        self._send_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/timing/config":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                payload = json.loads(raw or b"{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"ok": False, "error": "请求格式错误"})
                return
            self._send_json(200, timing_config_update(payload))
            return
        if path == "/api/timing":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                payload = json.loads(raw or b"{}")
                enabled = bool(payload.get("enabled"))
            except Exception:  # noqa: BLE001
                self._send_json(400, {"ok": False, "error": "请求格式错误"})
                return
            self._send_json(200, _set_timing_switch(enabled))
            return
        if path == "/api/orders/clear-pending":
            try:
                result = clear_pending_orders()
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, result)
            return
        if path == "/api/editor":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                payload = json.loads(raw or b"{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, save_editor_changes(payload))
            return
        if path != "/api/order":
            self._send_json(404, {"error": "not found"})
            return

        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            req = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            self._send_json(400, {"error": "请求格式错误"})
            return

        drink_type = req.get("type")
        if drink_type not in allowed_types():
            self._send_json(400, {
                "error": "不支持的饮品类型",
                "allowed": sorted(allowed_types()),
            })
            return
        # 禁用（缺货）饮品拒绝下单，并返回提示词
        try:
            for cat in load_menu().get("categories", []):
                for d in cat.get("drinks", []):
                    if d["type"] == drink_type and d.get("disabled"):
                        self._send_json(400, {"error": d.get("hint") or "该饮品暂时无法下单"})
                        return
        except Exception:  # noqa: BLE001
            pass

        try:
            quantity = int(req.get("quantity", 1))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "数量格式错误"})
            return
        if not (1 <= quantity <= MAX_QTY):
            self._send_json(400, {"error": f"数量需在 1-{MAX_QTY} 之间"})
            return

        try:
            result = add_order(drink_type, quantity)
        except Exception as exc:  # noqa: BLE001
            write_order_log({
                "time": datetime.now().isoformat(timespec="seconds"),
                "timestamp_ms": int(time.time() * 1000),
                "result": "error",
                "name": drink_cn_by_type(drink_type),
                "type": drink_type,
                "quantity": quantity,
                "pickup_codes": [],
                "order_ids": [],
                "client": self.client_address[0],
                "mode": "direct" if IN_CONTAINER else "bridge",
                "error": str(exc),
            })
            self._send_json(500, {"error": f"下单失败: {exc}"})
            return

        if not result.get("ok"):
            write_order_log({
                "time": datetime.now().isoformat(timespec="seconds"),
                "timestamp_ms": int(time.time() * 1000),
                "result": "error",
                "name": drink_cn_by_type(drink_type),
                "type": drink_type,
                "quantity": quantity,
                "pickup_codes": [],
                "order_ids": [],
                "client": self.client_address[0],
                "mode": result.get("mode", "unknown"),
                "error": "订单写入队列失败",
            })
            self._send_json(500, {"error": "订单写入队列失败"})
            return

        pickup_codes = result.get("pickup_codes", [])
        order_ids = result.get("order_ids", [])
        timestamp_ms = result.get("timestamp_ms") or int(time.time() * 1000)
        write_order_log({
            "time": datetime.now().isoformat(timespec="seconds"),
            "timestamp_ms": timestamp_ms,
            "result": "success",
            "name": drink_cn_by_type(drink_type),
            "type": drink_type,
            "quantity": quantity,
            "pickup_codes": pickup_codes,
            "order_ids": order_ids,
            "client": self.client_address[0],
            "mode": result.get("mode", "unknown"),
        })

        self._send_json(200, {
            "success": True,
            "name": drink_cn_by_type(drink_type),
            "type": drink_type,
            "quantity": quantity,
            "pickup_codes": pickup_codes,
            "order_ids": order_ids,
            "timestamp_ms": timestamp_ms,
            "time": datetime.now().isoformat(timespec="seconds"),
            "mode": result.get("mode", "unknown"),
        })

    def do_DELETE(self):
        path = urlparse(self.path).path
        prefix = "/api/orders/"
        if not path.startswith(prefix):
            self._send_json(404, {"error": "not found"})
            return
        order_id = path[len(prefix):]
        if not order_id:
            self._send_json(400, {"error": "缺少订单ID"})
            return
        try:
            result = delete_order(order_id)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if not result.get("ok"):
            err = result.get("error", "unknown")
            status = 404 if err == "not_found" else 400
            msg = "订单不存在" if err == "not_found" else "订单已开始制作，无法删除"
            self._send_json(status, {"ok": False, "error": msg})
            return
        self._send_json(200, result)


def lan_ips():
    """列出本机非回环 IPv4 地址（含热点接口）。"""
    result = []
    try:
        out = subprocess.check_output(["ifconfig"], text=True, errors="replace")
        current = None
        for line in out.splitlines():
            if re.match(r"^[a-zA-Z0-9]+:", line):
                current = line.split(":")[0]
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m and current and current != "lo0":
                ip = m.group(1)
                if not ip.startswith("127.") and ip not in {i for _, i in result}:
                    result.append((current, ip))
    except Exception:  # noqa: BLE001
        pass
    return result


def main():
    mode = "容器内直写 (COFFEE_DIRECT=1)" if IN_CONTAINER else f"主机桥接 (docker exec -> {CONTAINER})"
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    menu_summary = "菜单加载失败"
    try:
        menu = load_menu(force=True)
        menu_summary = " / ".join(c["name"] for c in menu.get("categories", [])) or "无可用分类"
    except Exception as exc:  # noqa: BLE001
        menu_summary = "加载失败: %s" % exc
    print("=" * 56)
    print("🤖 智魔方点单系统已启动")
    print(f"   运行模式: {mode}")
    print(f"   订单文件: {ORDER_FILE}")
    print("   菜单读取: 启动时一次性加载，之后不再动态读取")
    print(f"   动态菜单: {menu_summary}")
    print(f"   监听: 0.0.0.0:{PORT}")
    print("   其他设备访问地址：")
    for name, ip in lan_ips():
        print(f"     http://{ip}:{PORT}   ({name})")
    print("   本机测试: http://127.0.0.1:%d" % PORT)
    print("=" * 56)
    threading.Thread(target=_timing_observer_loop, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    main()
