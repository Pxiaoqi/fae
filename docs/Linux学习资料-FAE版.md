# Linux 学习资料（智平方 FAE 版）

> 目标：不是让你成为运维专家，而是让你具备 **"读懂系统、定位问题、写脚本提效"** 的能力。下面所有内容都按 FAE 场景裁剪，2–3 个月可完成主线。

---

## 一、FAE 为什么必须学 Linux（学到什么程度）

智平方的机器人控制主机基本都是 Linux（Ubuntu）环境，现场排障绕不开它。你需要达到的程度：

- 能看懂系统状态：进程、内存、磁盘、网络、GPU
- 能查日志：journalctl、dmesg、程序自己的日志文件
- 能配服务：systemd 开机自启、重启、看状态
- 能配网络：静态 IP、连通性测试、端口排查
- 能写脚本：批量改配置、解析日志、巡检告警
- 能远程干活：SSH、rsync、tmux
- 能用 Docker 进容器看日志（很多机器人软件跑在容器里）

---

## 二、四步学习路线

### 第 1 步：入门与常用命令（第 1–2 周）

**目标**：告别"用 Windows 的思路用 Linux"，掌握文件、权限、进程三大块。

**内容**：
- 目录结构与文件操作（ls / cd / cp / mv / rm / find / tree）
- 文件权限与用户（chmod / chown / sudo / 用户组）
- 查看文件（cat / less / head / tail -f）
- vim 基本操作（打开、编辑、保存、退出）
- 进程管理（ps / top / htop / kill）
- man 帮助与命令查询

**资料**：
- 鸟哥的 Linux 私房菜·基础学习篇（[linux.vbird.org](https://linux.vbird.org/linux_basic/)）——按章节刷前 12 章即可
- 尚硅谷 Linux 教程（B 站搜索"尚硅谷 Linux"），配合视频上手快
- 菜鸟教程 Linux（[runoob.com/linux](https://www.runoob.com/linux/linux-tutorial.html)）——当速查

**练习**：
- 在一台虚拟机/云服务器上完整装一遍 Ubuntu Server
- 每天用 man 查 3 个命令，坚持一周

### 第 2 步：文本处理与 Shell 脚本（第 2–3 周）

**目标**：能在日志里"捞"信息，能写脚本替代重复操作。

**内容**：
- 文本三剑客：grep（按模式过滤）、sed（批量替换）、awk（按列统计）
- 管道与重定向：|、>、>>、2>&1、tee
- Shell 脚本基础：变量、循环、条件判断、函数、cron 定时任务
- 实用工具：tar / zip 打包、rsync 同步、wget / curl

**资料**：
- 阮一峰 Bash 脚本教程（[wangdoc.com/bash](https://wangdoc.com/bash/)）——免费且完整
- 《Linux 命令行大全》（[linuxcommand.org](https://linuxcommand.org/)，有中文版）——命令行思维启蒙
- 《Linux 命令行与 Shell 脚本编程大全》第 4 版——想系统学脚本的备选

**练习**：
- 从一个 100MB 的机器人日志里统计 ERROR 出现次数和 TOP10 报错
- 用 sed 批量把一批 yaml 配置里的 IP 全部替换
- 写一个"磁盘/内存/温度巡检"脚本并加入 crontab

### 第 3 步：系统与服务管理（第 3–5 周）

**目标**：看懂机器人"为什么挂了、怎么让它自动恢复"。

**内容**：
- systemd：systemctl / journalctl，写一个自己的 .service 开机自启
- 磁盘与文件系统：df / du / fdisk / 挂载
- 系统资源：free / top / iostat / vmstat / 系统负载概念
- 设备与驱动：lsusb / lspci / dmesg / udev 规则（串口设备权限，机器人必踩）
- 日志体系：dmesg、journalctl、/var/log、日志轮转

**资料**：
- 《Linux 就该这么学》第 3 版（[linuxprobe.com](https://www.linuxprobe.com/)，在线免费读）——偏系统管理，边读边敲
- 鸟哥服务器篇（[linux.vbird.org/linux_server](https://linux.vbird.org/linux_server/)）——按需查网络与服务章节

**练习**：
- 给机器人主程序写一个 systemd 服务：崩溃自动重启、开机自动拉起、日志进 journald
- 给 USB 串口设备写 udev 规则，固定设备名
- 完整解读一次机器人宕机时的 dmesg + journalctl 日志链

### 第 4 步：网络与故障排查（第 5–8 周）

**目标**：具备"现场断连 10 分钟内定位"的能力。

**内容**：
- 网络基础：IP / 子网 / 网关 / DNS
- 配置与排查：ip / nmcli / netplan / ping / traceroute / ss
- 端口与服务：ss -tunlp、lsof -i、nc 测试端口
- 抓包入门：tcpdump（看 UDP/TCP 有没有通）
- 远程操作：SSH 密钥登录、scp / rsync、tmux 保持会话、跳板机
- Docker 基础：docker ps / logs / exec / 挂载目录 / --restart 策略

**资料**：
- 极客时间《Linux 性能优化实战》（倪朋飞）——第 4 步之后值得系统看，付费
- Docker 官方入门文档（[docs.docker.com/get-started](https://docs.docker.com/get-started/)）
- 阮一峰 Bash 教程里的网络章节 + 鸟哥服务器篇"网络基础"

**练习**：
- 现场模拟：断掉机器人网线，用 ip / ping / ss 三步定位断在哪一层
- 用 tcpdump 抓取机器人发往服务器的包，判断数据有没有发出去
- 用 tmux + rsync 完成一次跨机器的大日志同步
- 进机器人软件的 Docker 容器里定位一个崩溃问题

---

## 三、FAE 必会命令速查

| 分类 | 命令 | 优先级 |
| ---- | ---- | ---- |
| 日志 | tail -f / journalctl -u xxx -f / dmesg | 必须 |
| 进程 | ps -ef / top / htop / kill | 必须 |
| 系统 | free -h / df -h / uptime / uname -a | 必须 |
| 网络 | ip addr / ping / ss -tunlp / nc | 必须 |
| 文本 | grep -r / sed -i / awk | 必须 |
| 远程 | ssh / scp / rsync / tmux | 必须 |
| 磁盘 | du -sh * / fdisk -l / mount | 常用 |
| 设备 | lsusb / lspci / ls -l /dev/ttyUSB* | 常用 |
| 排查 | lsof / strace / tcpdump / iotop | 进阶 |
| 容器 | docker ps / logs / exec / inspect | 常用 |
| 帮助 | man / tldr / command --help | 必须 |

---

## 四、资料总表

| 分类 | 资料 | 类型 | 说明 | 优先级 |
| ---- | ---- | ---- | ---- | ---- |
| 入门书 | 《鸟哥的 Linux 私房菜·基础学习篇》 | 在线免费 | 华人圈经典，章节清晰 | ★★★ |
| 入门视频 | 尚硅谷 Linux（B 站） | 免费 | 跟着敲一遍，适合零基础 | ★★★ |
| 入门速查 | 菜鸟教程 Linux | 在线免费 | 命令查缺补漏 | ★★ |
| 脚本 | 阮一峰《Bash 脚本教程》 | 在线免费 | 最系统的中文脚本教程 | ★★★ |
| 命令思维 | 《Linux 命令行大全》 | 书（有中文版） | 理解命令行哲学 | ★★ |
| 脚本大全 | 《Linux 命令行与 Shell 脚本编程大全》 | 书 | 工具书，按需查 | ★★ |
| 系统管理 | 《Linux 就该这么学》 | 在线免费 | 面向 RHCE，系统管理实操 | ★★★ |
| 性能排障 | 极客时间《Linux 性能优化实战》 | 付费专栏 | 进阶必读，现场排查利器 | ★★（后学） |
| 实战闯关 | OverTheWire Bandit（[overthewire.org](https://overthewire.org/wargames/bandit/)） | 免费在线 | 游戏化练命令，强烈推荐 | ★★★ |
| 命令速查 | tldr（[tldr.sh](https://tldr.sh/)） | 免费工具 | man 太长的替代品 | ★★★ |
| 参考手册 | ArchWiki（[wiki.archlinux.org](https://wiki.archlinux.org/)） | 在线免费 | 任何发行版都能查，质量极高 | ★★★ |
| 脚本检查 | ShellCheck（[shellcheck.net](https://www.shellcheck.net/)） | 免费工具 | 检查脚本错误 | ★★ |
| 交互学习 | Linux Journey（[labex.io/linuxjourney](https://labex.io/linuxjourney)） | 在线免费 | 章节化 + 在线实操 | ★★ |

---

## 五、动手环境准备（任选其一，建议先有）

1. **云服务器轻量版**（阿里云 / 腾讯云，几十元/月）：随时随地上手，不怕搞坏
2. **WSL2**（Windows 电脑）：免费、和 Windows 共存，适合上班路上练习
3. **虚拟机**（VirtualBox / VMware）：装 Ubuntu Server，还原真实服务器环境
4. **公司工控机 / Jetson 真机**：最有价值，练手环境直接和产品一致

> 建议顺序：先云服务器/WSL2 入门 → 再在真机环境里实战。

---

## 六、结合机器人场景的 10 个实操题

1. 机器人主程序崩溃了，如何让它自动重启并记录日志？（systemd）
2. 现场机器人连不上服务器，用三步命令定位断在哪一层。
3. 100MB 日志里 ERROR 刷屏，怎么快速统计出 TOP10 报错？（grep / awk）
4. 一批机器人的 IP 配置要统一改，怎么用一条命令批量替换？
5. 机器人 USB 串口每次插拔设备名都变，怎么固定？（udev）
6. 机器人开机后某服务没起来，如何确认原因并设为自启？
7. 磁盘快满了，怎么找出最占空间的文件并安全清理？
8. 机器人摄像头/USB 设备识别不到，dmesg 该看什么？
9. 要远程拷贝一台机器人上的 bag 包，网速慢，怎么办？（rsync + tmux）
10. 机器人软件跑在 Docker 里，日志怎么看、崩溃怎么查？

---

## 七、学习节奏建议

- **每天 30–60 分钟**，主线 8 周完成，不追求一次吞完
- 每个命令学完立刻在真机上敲一遍，**动手 > 看视频**
- 第 3 周开始遇到问题优先自己查：`man` → `tldr` → ArchWiki → 搜索引擎
- 把每次现场排障用过的命令记进自己的速查笔记，形成个人知识库
- 学完第 4 步后，用 OverTheWire Bandit 通关一遍检验水平（每周 2–3 关）

---

## 八、下一步建议

Linux 是 FAE 学习路线第 0 阶段的一部分。按路线优先级，接下来可以依次整理：

- ROS / ROS2 学习资料
- 网络与工业通信（CAN / EtherCAT / TCP/IP）资料
- 传感器与标定资料
- 具身智能 / VLA 学习资料
