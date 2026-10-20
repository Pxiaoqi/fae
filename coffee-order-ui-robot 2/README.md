# 智魔方点单系统（机器人部署包）v1.0.0

## 场景可行性

可行。链路：

```
电脑浏览器（连机器人热点）
   │  http://<机器人IP>:8077
   ▼
点单服务 server.py（监听 0.0.0.0:8077）
   │  写入订单 JSON
   ▼
/root/AlphaBrainSystem/local/mqtt_orders.txt
   │  系统约 2 秒轮询
   ▼
机器人制作 → 出餐
```

## 前提条件（上机器人前逐项确认）

1. 容器内存在（与当前版本一致）：
   - `/root/AlphaBrainSystem/local/mqtt_orders.txt`（写入目标）
   - `/root/AlphaBrainSystem/tools/interfaces/coffee_order_manager_12.py`
   - `python3`
2. 端口 8077 在机器人/容器上未被占用（可用环境变量换端口）。
3. 网络可达：电脑连机器人热点后，能访问机器人（或容器）的 8077 端口。
   - 容器用 host 网络：直接访问机器人 IP。
   - 容器用 bridge 网络：需 `docker run -p 8077:8077` 发布端口，或改用主机模式。
4. 机器人热点不隔离客户端（设备间同网段可达）。

> 注意：在 Mac + Docker Desktop 上做本机测试时，宿主机直连容器 IP 可能不通
> （Docker Desktop 的桥接限制），这是测试环境差异；机器人上只要容器是
> host 网络、或发布了 `-p 8077:8077`，设备即可访问。功能本身已在容器内
> 以真实下单验证（订单写入队列、状态 pending、取餐码正常）。

## 两种部署方式

### 启动器（推荐）

```bash
./start.sh
```

启动时二选一：

- **1) 导入容器内运行（直写模式）**：把程序拷进容器并启动，
  订单列表/状态**每秒刷新**，实时性最好
- **2) 宿主机桥接运行**：不进入容器，订单状态 3 秒刷新

也可非交互指定：`./start.sh --direct --container coffee-v2.2.5 --port 8077`
或 `./start.sh --bridge --container coffee-v2.2.5 --port 8077`。

### 一键启动（首次配置后免交互）

首次运行会保存 `.startup.conf` 并自动生成 `quickstart.sh`：

- 宿主机再次启动：`./quickstart.sh`（或直接 `./start.sh`，自动用上次配置）
- 容器内一键启动：`cd /opt/coffee-order-ui && ./quickstart.sh`
- 重新配置：`./start.sh --wizard`
- 只查端口：`./start.sh --check`

### 方式 A：容器内直写（推荐）

```bash
./deploy_to_container.sh coffee-v2.2.5 /opt/coffee-order-ui
```

把文件复制进容器并启动（`COFFEE_DIRECT=1`），
点单服务在容器内直接写订单文件，不依赖宿主机 docker CLI。
重启容器后需重新执行本脚本（或把启动命令加入容器启动流程）。

### 方式 B：主机桥接（点单服务在机器人宿主机）

```bash
./start_host.sh coffee-v2.2.5 8077
```

宿主机需安装 docker CLI 且有权限执行 `docker exec`。
开机自启可安装 systemd 服务（按需改容器名/路径）：

```bash
sudo cp coffee-order-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now coffee-order-ui
```

## 配置项

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `COFFEE_DIRECT` | `1`=容器内直写；不设=主机桥接 | 无 |
| `COFFEE_UI_PORT` | 监听端口 | 8077 |
| `COFFEE_CONTAINER` | 容器名（桥接模式） | coffee-v2.1.6 |
| `COFFEE_MANAGER_DIR` | 容器内下单模块目录 | /root/AlphaBrainSystem/tools/interfaces |
| `COFFEE_ORDER_FILE` | 订单文件（直写兜底用） | /root/AlphaBrainSystem/local/mqtt_orders.txt |

## 页面说明

- 动态分类 tab：咖啡 / 冰激凌 / 啤酒 / 鸡尾酒，点 tab 切换，页面自动
  读取容器内 `PIPELINE.yaml` + `INTERFACES.yaml` 生成菜单。
- 当前机器人制作内容由 `PIPELINE.yaml` 的 `active_behavior_tree` 与
  `robot_profile` 决定，默认选中对应分类（如 RobotB → 咖啡）。
- 咖啡分类内部按 黑咖 / 奶咖 / 清水 三组配色区分（`color_groups` 可配）。
- 点击卡片即下单 1 杯，弹出取餐码；1 秒内重复点击被拦截。
- 右上角状态灯：绿色=服务与下单通道正常；红色=容器/模块连接异常。
- 纯净点单模式：`?pure=1` 或右上角 ⛶，全屏只显示卡片，方向键/滑动切分类。

## 菜单配置文件 menu_config.yaml

`menu_config.yaml` 定义 TEMPLATE-X.yaml 与点单分类的绑定：

- `categories[].templates`：该分类绑定的模板文件（须出现在 PIPELINE.yaml
  的 `behavior_tree_template_files` 中才会显示该分类）
- `categories[].check_node`：INTERFACES.yaml 中对应分类的校验节点，
  其 `target_values` 即该分类可下单的饮品
- `behavior_trees`：`active_behavior_tree` → 默认选中的分类
- `default_category_by_robot`：按 `robot_profile` 的 `robot.id` 决定默认模块
- `alcohol_types`：标注"⚠ 含酒精"的 type 列表

接口：`GET /api/menu` 返回动态菜单 JSON（仅在服务启动时读取一次
容器配置并缓存，之后不再动态读取；编辑弹窗保存只改本地覆盖文件）。

## 最近下单与订单日志

- 每次下单都会追加写入 `orders.log`（JSON Lines，UTF-8），记录下单时间
  （容器/服务端时间，精确到毫秒）、饮品、type、数量、取餐码、订单号、
  来源 IP、运行模式；失败订单也会记录错误原因。
- 订单日志覆盖完整生命周期事件：
  - `success`：下单成功
  - `completed`：订单完成（服务端通过订单状态缓存检测，每单仅记录一次）
  - `deleted`：单笔删除
  - `cleared`：一键清除
  - `error`：下单失败
- 服务端内置订单状态缓存（内存），配合队列轮询实时更新，
  无需每次现读现算。
- 日志文件位置可用环境变量 `COFFEE_ORDERS_LOG` 修改，默认在应用目录下。

## 订单管理

- **待制作订单**：页面展示当前队列中未制作（pending）的订单，可单笔删除，
  也可"一键清除所有未制作订单"
  - `GET /api/orders/pending`：待制作列表
  - `DELETE /api/orders/{order_id}`：删除单笔未制作订单
  - `POST /api/orders/clear-pending`：一键清除所有未制作订单
- **最近完成**：只展示最近制作完成的最新 3 笔，按时间倒序
  （`GET /api/orders/recent?limit=3`，服务端过滤已完成订单）
- 订单完成（进入制作后出队/状态变为完成）时页面自动弹出提示，每单一次

## 制作时长监听（cerebrum.log，v2.2.5）

- 只读监听机器人 `logger/<日期>/<时-分>/cerebrum/cerebrum.log`，
  不改容器任何代码，仅新增 `timing_config.yaml` 与观察器
- 测量口径：**"转身开始制作订单"（move_torso_to_*_default_*）→
  "送餐张开夹爪"（move_left_gripper_to_open，兼容 _1/_2/_before_bottle/_start 后缀变体）**
- 起止节点规则在 `timing_config.yaml` 中配置，容器内可在今日订单抽屉
  在线修改（`GET/POST /api/timing/config`），保存后热生效
- **失败判定**：动作未正常闭环且订单消失（或关闭订单状态为
  failed/cancelled）→ 记录为"制作失败"（result=failed），不计入平均时长
- 结果写入应用目录 `order_times.log`（JSONL），接口
  `GET /api/orders/times?limit=N` 返回最近耗时与平均时长
- "今日订单"抽屉展示平均制作时长与最近 3 笔耗时
- 配置项：`timing_config.yaml`（日志目录 glob、起点/终点节点规则、
  闭环判定文件、失败终态、回补天数、单笔最长阈值、轮询间隔）；
  单笔超过 1 小时标记为可疑不计入平均
- 制作时长开关与规则修正仅在**容器内直写模式**可用；
  桥接模式下整个制作时长功能隐藏、接口拒绝修改

## 测试

```bash
# 健康检查
curl http://127.0.0.1:8077/api/health

# 下单测试（type 17-21）
curl -X POST http://127.0.0.1:8077/api/order \
  -H 'Content-Type: application/json' \
  -d '{"type": 17, "quantity": 1}'

# 查看队列
cat /root/AlphaBrainSystem/local/mqtt_orders.txt
```
