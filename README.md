# arm-true 使用说明

## 目标

这是一个面向机械臂调参的轻量工具，支持在本地或 Docker 外部环境中读取 Docker 容器内的配置文件，并通过 Web 页面或键盘控制进行简单调试。

## 依赖情况

当前项目不依赖任何额外的第三方 Python 包，默认只使用 Python 标准库。

## 快速开始

1. 进入项目目录：
   ```bash
   cd /root/AlphaBrainSystem/configs/behavior/COFFEE/arm-true
   ```

2. 创建本地虚拟环境（可选，但推荐）：
   ```bash
   bash install_dependencies.sh
   ```

3. 直接使用启动脚本启动 Web 控制页面：
   ```bash
   ./run_arm_web.sh
   ```

   如果你想指定容器名，也可以：
   ```bash
   ./run_arm_web.sh --docker <container_name>
   ```

## 配置项说明

只需要填一个 Docker 容器名即可：

```bash
--docker <container_name>
```

如果你想同时指定配置文件路径，也可以：

```bash
./run_arm_web.sh --docker <container_name> --arm-config /root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml
```

如果你不想每次都写参数，也可以直接用环境变量：

```bash
ARM_DOCKER_CONTAINER=<container_name> \
ARM_CONFIG_PATH=/root/AlphaBrainSystem/configs/behavior/COFFEE/ARM.yaml \
./run_arm_web.sh
```

## 配置目录浏览功能

启动 Web 页面后，页面中“配置目录浏览”区域默认会指向 Docker 容器内的目录：

```bash
/root/AlphaBrainSystem/configs/behavior/COFFEE/
```

你可以：
- 直接点击目录项进入子目录
- 点击文件项在编辑器中加载其内容
- 通过上一级按钮回退到上层目录

## 参数联动查询功能

页面中的“参数联动查询”区域可以根据关键字搜索 ARM.yaml 中的参数块。比如输入：

```bash
move_arm_to_default_F
```

点击查询后，系统会：
- 在 ARM.yaml 中匹配相关参数块
- 在编辑器中显示对应内容
- 允许你修改后点击“替换当前 ARM 块”进行更新

注意：如果当前是 Docker 外部环境运行，必须通过 `--docker <container_name>` 指定目标容器，否则会按本地路径处理。

## 运行键盘控制脚本

```bash
./.venv/bin/python arm-true.py left
```

按键方向与 Web 控制台一致（物理坐标）：W/S=Y（深/浅）、A/D=Z（左/右）、Q/E=X（上/下），
R 复位、F 查看关节、T 查看位移、Space 急停。

## 说明

- 默认优先使用你显式提供的 ARM.yaml 路径。
- 如果指定了 Docker 容器，则会优先通过 Docker 执行读取配置文件。
- 如果没有指定容器，则会回退到本地文件系统。
- 机械臂运动使用 RealMan JSON 协议的 `movel`（笛卡尔直线运动）指令，
  保证沿 X/Y/Z 单轴直线移动；每次移动都以机械臂当前实际位姿为基准叠加增量，
  避免多次移动累积误差。
- 如果机械臂不在线，Web 页面会自动进入模拟模式，配置文件浏览与编辑功能仍可使用。
- 启动或切换 Docker 容器时，程序会读取 PIPELINE.yaml 的 `active_behavior_tree`
  （RobotB/C/D/E/F 分别对应咖啡机/冰激凌机/新冰激凌机/啤酒机/鸡尾酒机），
  「动作调参」分组只展示对应机器人的动作；读取失败时回退为显示全部分组。
- 在「动作调参」中选择动作后，会在对应机器人的 TEMPLATE-*.yaml（如 RobotC ->
  TEMPLATE-C.yaml，RobotE_LKF -> TEMPLATE-E-LKF.yaml）中所选节点的下一行插入
  `- "sleep_for_120s"` 暂停；切换其他动作时旧暂停会被删除并迁移到新动作处，
  模板中始终保持一条 `sleep_for_120s`。
- 相关脚本文件：
  - arm_web_server.py
  - arm-true.py
  - arm_controller.py
  - arm_config_utils.py

## 验证

可以运行以下测试进行基础验证：

```bash
python3 -m unittest discover -s tests -v
```

## 机器人端部署与更新

本分支为机器人调参专用分支，只包含本项目内容。机器人端只需拉取本分支，不会下载仓库中的其他文件。

首次部署（在机器人上执行）：

```bash
sudo mkdir -p /root/AlphaBrainSystem/configs/behavior/COFFEE
git clone -b tuning --single-branch --depth 1 git@github.com:Pxiaoqi/fae.git \
  /root/AlphaBrainSystem/configs/behavior/COFFEE/arm-true
```

日常更新（在机器人上执行）：

```bash
cd /root/AlphaBrainSystem/configs/behavior/COFFEE/arm-true
git pull
```

说明：

- 仓库为私有仓库，机器人需要配置只读 SSH deploy key（或改用公开仓库 / 带凭据的 https 地址）
- 若现场无法直连 GitHub，可配置代理后重试，或改用 raw 文件下载方式
