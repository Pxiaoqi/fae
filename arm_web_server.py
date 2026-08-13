#!/usr/bin/env python3
"""为机械臂提供一个轻量级 Web 控制页面。"""

import argparse
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_VENV_PYTHON = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
if os.path.exists(LOCAL_VENV_PYTHON) and sys.executable != LOCAL_VENV_PYTHON:
    sys.path.insert(0, os.path.join(SCRIPT_DIR, ".venv", "lib", "python" + sys.version.split()[0].split(".")[0] + "." + sys.version.split()[0].split(".")[1], "site-packages"))

from arm_config_utils import ArmConfigHelper
from arm_controller import ArmController

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8001"))
DEFAULT_DOCKER_NAME = os.getenv("ARM_DOCKER_CONTAINER", "coffee-v2.1.7")

controllers: Dict[str, ArmController] = {}
config_helper = ArmConfigHelper(
    base_dir=os.path.join(os.path.dirname(__file__), ".."),
    arm_config_path=os.getenv("ARM_CONFIG_PATH") or os.getenv("ARM_YAML_PATH")
)


def get_controller(arm_name: str = "left") -> ArmController:
    arm_name = arm_name.lower() if arm_name else "left"
    if arm_name not in {"left", "right"}:
        arm_name = "left"
    if arm_name not in controllers:
        kwargs = {
            "arm_name": arm_name,
            "ip": os.getenv("LEFT_ARM_IP" if arm_name == "left" else "RIGHT_ARM_IP", "192.168.1.18" if arm_name == "left" else "192.168.1.19"),
            "port": int(os.getenv("ARM_PORT", "8080")),
        }
        controller = ArmController(**kwargs)
        if not controller.connect():
            print(
                f"⚠️ 无法连接机械臂 {controller.ip}:{controller.port} "
                f"({controller.last_error or 'unknown error'})，已切换为模拟模式，配置浏览仍可用"
            )
            controller = ArmController(simulate=True, **kwargs)
            controller.connect()
        controllers[arm_name] = controller
    return controllers[arm_name]


class ArmWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        arm_name = params.get("arm", ["left"])[0]
        if parsed.path in {"/", "/index.html"}:
            self._serve_file("index.html", content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            self._send_json(get_controller(arm_name).get_state())
            return
        if parsed.path == "/api/joints":
            self._send_json(get_controller(arm_name).get_state())
            return
        if parsed.path == "/api/docker/containers":
            self._send_json({
                "ok": True,
                "containers": ArmConfigHelper.list_docker_containers(),
                "default": os.getenv("ARM_DOCKER_CONTAINER") or "",
            })
            return
        if parsed.path == "/api/actions":
            container = params.get("container", [None])[0]
            self._send_json(config_helper.list_actions(container=container))
            return
        if parsed.path == "/api/actions/approach":
            action_id = params.get("id", [""])[0]
            container = params.get("container", [None])[0]
            self._send_json(config_helper.get_action_value(action_id, container=container))
            return
        if parsed.path == "/api/config/dir":
            path = params.get("path", [None])[0]
            container = params.get("container", [None])[0]
            self._send_json(config_helper.list_directory(path, container=container))
            return
        if parsed.path == "/api/config/file":
            path = params.get("path", [None])[0]
            container = params.get("container", [None])[0]
            self._send_json(config_helper.read_text_file(path or "", container=container))
            return
        if parsed.path.startswith("/static/"):
            name = parsed.path.split("/", 2)[-1]
            self._serve_file(name, content_type="text/plain; charset=utf-8")
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "请求体不是合法 JSON"}, status=400)
            return
        if not isinstance(data, dict):
            self._send_json({"ok": False, "error": "请求体必须是 JSON 对象"}, status=400)
            return

        arm_name = data.get("arm") or params.get("arm", ["left"])[0]
        arm = get_controller(arm_name)

        if parsed.path == "/api/move":
            try:
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                dz = float(data.get("dz", 0.0))
                speed = float(data.get("speed", 20.0))
            except (TypeError, ValueError):
                self._send_json(
                    {
                        "ok": False,
                        "error": (
                            "无效的移动参数，dx/dy/dz/speed 必须为数字: "
                            f"dx={data.get('dx')!r} dy={data.get('dy')!r} "
                            f"dz={data.get('dz')!r} speed={data.get('speed')!r}"
                        ),
                    },
                    status=400,
                )
                return
            state = arm.move(dx=dx, dy=dy, dz=dz, speed=speed)
            self._send_json({"ok": not state.get("error"), "state": state})
            return

        if parsed.path == "/api/reset":
            self._send_json({"ok": True, "state": arm.reset()})
            return

        if parsed.path == "/api/stop":
            self._send_json({"ok": True, "state": arm.emergency_stop()})
            return

        if parsed.path == "/api/config/save-file":
            path = data.get("path", "")
            content = data.get("content", "")
            container = data.get("container") or params.get("container", [None])[0]
            self._send_json(config_helper.write_text_file(path, content, container=container))
            return

        if parsed.path == "/api/actions/save":
            config = data.get("config")
            self._send_json(ArmConfigHelper.save_actions(config))
            return

        if parsed.path == "/api/actions/approach":
            action_id = data.get("id", "")
            waypoints = data.get("waypoints", [])
            container = data.get("container") or params.get("container", [None])[0]
            self._send_json(config_helper.update_action_value(action_id, waypoints, container=container))
            return

        if parsed.path == "/api/actions/pause":
            action_id = data.get("id", "")
            container = data.get("container") or params.get("container", [None])[0]
            self._send_json(config_helper.set_action_pause(action_id, container=container))
            return

        self._send_json({"ok": False, "error": "unsupported action"}, status=400)

    def log_message(self, format, *args):
        return

    def _serve_file(self, filename: str, content_type: str):
        path = os.path.join(os.path.dirname(__file__), filename)
        if not os.path.exists(path):
            self._send_json({"ok": False, "error": "file not found"}, status=404)
            return
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="机械臂 Web 控制服务")
    parser.add_argument("--host", default=HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=PORT, help="监听端口")
    parser.add_argument("--docker", dest="docker_name", default=None, help="Docker 容器名称")
    parser.add_argument("--arm-config", dest="arm_config", default=None, help="指定 ARM.yaml 的绝对路径")
    return parser


def _find_free_port(host: str, preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, preferred_port))
            return preferred_port
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def main() -> None:
    args = build_parser().parse_args()
    docker_name = args.docker_name or os.getenv("ARM_DOCKER_CONTAINER") or DEFAULT_DOCKER_NAME
    os.environ["ARM_DOCKER_CONTAINER"] = docker_name
    if args.arm_config:
        os.environ["ARM_CONFIG_PATH"] = args.arm_config

    port = _find_free_port(args.host, args.port)
    server = ThreadingHTTPServer((args.host, port), ArmWebHandler)
    print(f"🌐 Web 页面已启动: http://{args.host}:{port}/")
    try:
        get_controller()
        active = config_helper.get_active_behavior_tree()
        if active.get("ok"):
            print(f"🤖 active_behavior_tree: {active['value']} -> {active['label']}（{active['device']}）")
        else:
            print(f"⚠️ 未能读取 active_behavior_tree: {active.get('error')}")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
