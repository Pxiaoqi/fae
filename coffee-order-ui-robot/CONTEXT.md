# 智魔方点单系统 v1.0.0 · 上下文与部署说明

> 本文件随代码一起交付，供机器人在现场测试、修改时查阅。

## 1. 系统概述

- 用途：机器人吧台场景，顾客用手机/电脑连机器人热点，打开点单页下单，
  机器人自动制作饮品。
- 订单协议：点单服务把订单写入
  `/root/AlphaBrainSystem/local/mqtt_orders.txt`（JSON 字典），
  机器人系统约 2 秒轮询该文件接单制作，并把 `status` 字段实时更新回文件。
- 制作时长：只读监听机器人 `cerebrum.log`，按"转身开始制作 → 送餐张开夹爪"
  两个动作节点计算。

## 2. 总体架构与数据流

```
设备浏览器(连机器人热点)
   │  http://<机器人IP>:8077
   ▼
点单服务 server.py（0.0.0.0:8077）
   ├── 菜单：启动时读一次容器配置（PIPELINE/INTERFACES/robot_profile/menu_config）
   ├── 下单：写 mqtt_orders.txt（status=pending）
   ├── 状态：读 mqtt_orders.txt（直写 1s / 桥接 2s 缓存）→ 页面轮询刷新
   ├── 日志：orders.log（success/completed/deleted/cleared/error）
   ├── 统计：今日订单、最近完成 3 笔
   └── 制作时长：后台线程只读 logger/.../cerebrum.log → order_times.log
   ▼
机器人系统 OrderQueueCondition / MqttOrderBridge（约 2s 轮询）
   ▼
行为树执行（TEMPLATE-*）→ 制作 → 状态更新/移入 mqtt_closed_orders.txt
```

## 3. 文件说明（11 个交付文件）

| 文件 | 说明 |
| --- | --- |
| server.py | 点单服务（双模式：直写/桥接；含制作时长观察器） |
| index.html / app.js / style.css | 前端页面 |
| menu_config.yaml | 模板↔分类绑定、布局、配色分组、酒精、默认模块 |
| timing_config.yaml | 制作时长起止节点规则、闭环判定文件、失败终态 |
| start.sh | 交互式启动器（1 直写 / 2 桥接，自动端口转发） |
| deploy_to_container.sh | 一键部署进容器（直写模式） |
| coffee-order-ui.service | 主机桥接模式 systemd 自启（可选） |
| README.md / CONTEXT.md | 说明与上下文 |

## 4. 运行模式

| 项 | 直写模式（推荐，机器人） | 桥接模式（Mac 演示） |
| --- | --- | --- |
| 设置 | `COFFEE_DIRECT=1`，程序跑在容器内 | 不设置，程序跑在宿主机 |
| 下单 | 进程内调用容器模块，毫秒级 | 每次 `docker exec` 冷启动 Python |
| 订单状态刷新 | 1 秒 | 3 秒 |
| 制作时长监听 | 可用（可开关、可改规则） | **隐藏且禁止开启/修改** |
| 部署 | `./start.sh` 选 1 | `./start.sh` 选 2 |

端口可达性：容器 host 网络直接访问机器人 IP:8077；bridge 网络需
`-p 8077:8077` 或由 `start.sh` 自动创建 alpine 转发旁路容器
（`coffee-ui-fwd-8077`）。

## 5. 容器侧依赖（零改动，只读）

程序**不修改任何容器代码**，只读取：

- `configs/behavior/COFFEE/PIPELINE.yaml`（模板清单、行为树、robot_profile）
- `configs/behavior/COFFEE/INTERFACES.yaml`（task_mapping、check_*_task）
- `configs/calib/<robot>/robot_profile.yaml`（robot.id）
- `configs/behavior/COFFEE/log_stage_map.yaml`（节点→阶段，仅参考）
- `logger/<日期>/<时-分>/cerebrum/cerebrum.log`（制作时长监听）
- `local/mqtt_orders.txt` / `local/mqtt_closed_orders.txt`（订单/闭环判定）

写入：

- `local/mqtt_orders.txt`（下单/删除/清除——机器人系统本来就期望写入的文件）
- 应用自己的 `orders.log`、`order_times.log`、`menu_overrides.json`、
  `timing_switch.json`、`timing_config.yaml`（均在应用目录，不在容器系统内）

## 6. v2.2.5 日志方案与制作时长

- 日志结构：`logger/<YYYY-MM-DD>/<HH-MM>/...`（30 分钟时间桶，保留 14 天，
  Asia/Shanghai），路由含 `cerebrum/cerebrum.log`、`interfaces/mqtt.log` 等。
- cerebrum.log 事件行（毫秒级）：
  ```
  2026-08-23 12:34:02.269 [INFO] [behavior/order_queue] event=ORDER_SELECTED
    status=success order=order_xxx task=latte stage=ORDER_SELECTED
  ... event=MOTION_COMMAND_SENT ... node_name=move_torso_to_cup_popper_default_B
  ... event=ORDER_REPORT_SENT ... node_name=order_status_report_success
  ... event=ORDER_FINISHED ... order_status=completed actual_start_time=...
  ```
- 测量口径（timing_config.yaml 可改）：
  - 起点：`ORDER_SELECTED` 之后第一个
    `move_torso_to_*_default_*`（转身开始制作，正则 `^move_torso_to_(?!send_meal)`）
  - 终点：送餐转身后的 `move_left_gripper_to_open`（送餐张开夹爪）
    实际日志节点带编号后缀（如 `_1`/`_2`/`_before_bottle`/`_start`），
    规则已兼容全部变体
- 失败判定：动作未闭环且订单消失，或关闭订单状态为
  failed/cancelled/auto_cancelled → 记为 `result=failed`，不计平均。
- 开关：今日订单抽屉可关/开（仅直写模式）；关闭期间不记录。
- 规则修正：抽屉内可在线改起止节点正则（写回 timing_config.yaml 热生效）。

## 7. 配置与环境变量

`menu_config.yaml`：categories（templates/check_node/layout/color_groups）、
behavior_trees、default_category_by_robot、alcohol_types。

`timing_config.yaml`：log_glob、backfill_days、start/end 规则、
closed_orders_file、active_orders_file、failed_statuses、max_duration_sec、poll_sec。

环境变量：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| COFFEE_UI_PORT | 端口 | 8077 |
| COFFEE_DIRECT | 1=容器内直写 | 无 |
| COFFEE_CONTAINER | 容器名（桥接） | coffee-v2.1.6 |
| COFFEE_ORDERS_LOG | 订单日志路径 | <应用目录>/orders.log |
| COFFEE_ORDER_TIMES_LOG | 制作时长日志 | <应用目录>/order_times.log |
| COFFEE_TIMING_CONFIG | 时长配置路径 | <应用目录>/timing_config.yaml |

运行时文件：`menu_overrides.json`（编辑保存的绑定/布局/当前模块）、
`timing_switch.json`（时长开关）。重建容器前请备份。

## 8. 部署步骤（机器人）

```bash
# 拷贝 zip 到机器人，解压
unzip coffee-order-ui-robot-v1.0.0-完整包.zip
cd coffee-order-ui-robot
./start.sh          # 选 1：导入容器直写（推荐）
# 设备连机器人热点，打开 http://<机器人IP>:8077
```

验证：`curl http://127.0.0.1:8077/api/health` 返回 docker_ok。
可选自启（主机桥接）：`sudo cp coffee-order-ui.service /etc/systemd/system/ && sudo systemctl enable --now coffee-order-ui`。

首次配置后生成一键脚本（免交互）：
- 宿主机：`./quickstart.sh` 或直接 `./start.sh`
- 容器内：`cd /opt/coffee-order-ui && ./quickstart.sh`
- 重新配置：`./start.sh --wizard`

## 9. 现场测试清单

1. 页面加载、4 分类菜单、咖啡三组配色（黑咖/奶咖/清水）
2. 点击下单 ≤ 数秒出取餐码；1 秒内连点被拦截
3. 待制作列表出现新单；机器人开始制作后状态变"制作中"
4. 制作中订单点删除被拒；pending 订单可删；一键清除可用
5. 完成后进入"最近完成"（最新 3 笔倒序），页面弹"已完成"
6. 今日订单抽屉：总笔数、各饮品数量、平均制作时长、最近 3 笔耗时
7. 制作时长开关可关/开；起止规则可在线改并热生效
8. 编辑弹窗：改绑定/布局/当前模块，保存后菜单实时更新，多分类修改互不覆盖
9. 纯净模式（⛶ 或 ?pure=1）只显示卡片，方向键/滑动切分类
10. 桥接模式（如用）：制作时长功能隐藏、接口拒绝
11. 机器人断电重启后：容器内点单服务需重跑 `./start.sh` 选 1

## 10. 已知边界与注意事项

- 订单文件"读-改-写"无文件锁（机器人侧同款），并发写有短暂覆盖窗口，
  但双方都保留活动订单，最终一致。
- 竞态：删除"pending"订单时若机器人刚选中该单（内存 executing），
  删除可能无效（机器人会写回），不影响制作。
- 日志 30 分钟轮转，观察器自动跟随新时间桶；回补最近 2 天。
- 时长超 1 小时标记 suspicious，不计平均。
- 端口 8077 被占用时用 `COFFEE_UI_PORT` 换端口（前端同源自动适配）。
- 首次启动菜单读取/模块导入较慢（几秒~几十秒），属正常。

## 11. 版本记录

- v1.0.0：功能全量交付（动态菜单、订单管理、统计、制作时长监听、
  编辑弹窗、纯净模式、双模式部署、失败判定）。
