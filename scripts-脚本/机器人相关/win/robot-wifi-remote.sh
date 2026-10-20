#!/bin/bash
# ============================================================
#  机器人 Wi-Fi 连接助手 —— 机器人端临时脚本
#
#  由 Windows 端「一键连接机器人WiFi.cmd」通过 ssh 临时投放到 /tmp 执行，
#  跑完立即删除自身；不安装任何软件、不修改机器人任何配置。
#
#  做的事（和 mac 版一致）：
#    sudo nmcli dev wifi list          扫 Wi-Fi
#    sudo nmcli dev wifi connect ...   连 Wi-Fi
#    ping www.baidu.com                校验是否真的通网
# ============================================================

ROBOT_IP='__ROBOT_IP__'
DEF_PASS='__DEFAULT_WIFI_PASS__'
WAIT_MAX=8          # 校验网络最多试几次
WAIT_SEC=5          # 每次间隔秒数

# 退出时删掉自己（Windows 端 ssh 命令行里也删一次，双保险）
trap 'rm -f "$0" 2>/dev/null' EXIT

# ---------------- 输出 ----------------
ESC=$(printf '\033')
C_CYAN="${ESC}[36m"
C_GREEN="${ESC}[32m"
C_RED="${ESC}[31m"
C_YEL="${ESC}[33m"
C_RST="${ESC}[0m"
say()  { printf '\n%s▶ %s%s\n' "$C_CYAN" "$1" "$C_RST"; }
ok()   { printf '%s✔ %s%s\n' "$C_GREEN" "$1" "$C_RST"; }
err()  { printf '%s✘ %s%s\n' "$C_RED" "$1" "$C_RST"; }
warn() { printf '%s! %s%s\n' "$C_YEL" "$1" "$C_RST"; }
hr()   { printf '%s\n' '------------------------------------------------------------'; }

# ---------------- 键盘输入 ----------------
_ans=""
ask_line() {                 # $1=提示语，结果放 $_ans
    printf '%s' "$1"
    IFS= read -r _ans
    _ans=$(printf '%s' "$_ans" | tr -d '\r')
}
ask_secret() {               # $1=提示语，结果放 $_ans（不回显）
    printf '%s' "$1"
    IFS= read -r -s _ans
    printf '\n'
    _ans=$(printf '%s' "$_ans" | tr -d '\r')
}

# ---------------- sudo ----------------
SUDO_PW=""
SUDO_READY=0
sudo_prepare() {
    [ "$SUDO_READY" = 1 ] && return 0
    if sudo -n true 2>/dev/null; then
        SUDO_READY=1
        return 0
    fi
    ask_secret '需要机器人密码来做 sudo，请输入一次（之后自动使用）：'
    SUDO_PW="$_ans"
    if ! printf '%s\n' "$SUDO_PW" | sudo -S -p '' true 2>/dev/null; then
        err 'sudo 密码不正确'
        SUDO_PW=""
        return 1
    fi
    SUDO_READY=1
    return 0
}
srun() { printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"; }

# ---------------- 扫描 ----------------
# 输出：信号 <TAB> SSID <TAB> 加密（按信号从高到低，已按 SSID 去重）
scan_lines() {
    srun nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list 2>/dev/null \
        | sed 's/\\:/'"$(printf '\001')"'/g' \
        | awk -F: '
            NF >= 3 && $1 != "" {
                s = $2 + 0
                if (!($1 in seen)) { n++; order[n] = $1; seen[$1] = 1 }
                if (!($1 in best) || s > best[$1]) { best[$1] = s; sec[$1] = $3 }
            }
            END { for (i = 1; i <= n; i++) printf "%d\t%s\t%s\n", best[order[i]], order[i], sec[order[i]] }
          ' \
        | sort -k1,1nr \
        | sed 's/'"$(printf '\001')"'/:/g'
}

# ---------------- 选择 Wi-Fi ----------------
SSID=""
WPASS=""

ask_pass() {                 # $1=SSID
    ask_secret "请输入 $1 的密码（回车=默认 $DEF_PASS，输入 - 表示无密码）："
    case "$_ans" in
        '-') WPASS="" ;;
        '')  WPASS="$DEF_PASS" ;;
        *)   WPASS="$_ans" ;;
    esac
}

pick_manual() {
    ask_line '请输入 Wi-Fi 名称（SSID）：'
    SSID="$_ans"
    if [ -z "$SSID" ]; then
        err 'SSID 不能为空'
        return 1
    fi
    ask_pass "$SSID"
    return 0
}

pick_from_list() {
    while :; do
        say 'wifi搜索中 ...'
        LIST=$(scan_lines)
        if [ -z "$LIST" ]; then
            err '没有扫描到 Wi-Fi。'
            printf '  可能原因：网卡未启用 / 离路由器太远 / nmcli 不可用\n'
            ask_line '按 r 重新扫描，按 m 手动输入，按 q 退出：'
            case "$(printf '%s' "$_ans" | tr 'A-Z' 'a-z')" in
                m) pick_manual && return 0 ;;
                q) printf '已取消。\n'; exit 0 ;;
                *) continue ;;
            esac
        fi
        printf '\n  编号  Wi-Fi 名称                        信号    加密\n'
        printf '  ----  --------------------------------  ------  ------------\n'
        i=0
        while IFS=$'\t' read -r sig ssid sec; do
            i=$((i + 1))
            printf '  %4d  %-32.32s  %4s%%  %s\n' "$i" "$ssid" "$sig" "$sec"
        done <<< "$LIST"
        printf '\n'
        ask_line '请输入要连接的 Wi-Fi 编号（r=重新扫描，m=手动输入，q=退出）：'
        choice=$(printf '%s' "$_ans" | tr 'A-Z' 'a-z')
        case "$choice" in
            r) continue ;;
            m) pick_manual && return 0 ;;
            q) printf '已取消。\n'; exit 0 ;;
        esac
        case "$choice" in
            ''|*[!0-9]*) err '输入无效，请重新输入。'; continue ;;
        esac
        if [ "$choice" -lt 1 ] || [ "$choice" -gt "$i" ]; then
            err '输入无效，请重新输入。'
            continue
        fi
        line=$(printf '%s\n' "$LIST" | sed -n "${choice}p")
        SSID=$(printf '%s' "$line" | cut -f2)
        SEC=$(printf '%s' "$line" | cut -f3)
        case "$SEC" in
            *WPA*|*wpa*|*WEP*|*wep*|*802.1X*)
                ask_pass "$SSID"
                return 0 ;;
            *)
                printf '该 Wi-Fi 是开放网络（无加密），直接连接。\n'
                WPASS=""
                return 0 ;;
        esac
    done
}

# ============================================================
#                          主流程
# ============================================================
printf '%s\n' '============================================================'
printf '               机器人 Wi-Fi 连接助手\n'
printf '               设备：%s\n' "$ROBOT_IP"
printf '%s\n' '============================================================'

# ---------- 1. 选择连接方式 ----------
while :; do
    hr
    printf '请选择 Wi-Fi 连接方式：\n'
    printf '  1) 手动输入 Wi-Fi 名称和密码\n'
    printf '  2) 扫描并选择附近的 Wi-Fi\n'
    printf '  q) 退出\n'
    ask_line '请输入 1 / 2 / q：'
    case "$(printf '%s' "$_ans" | tr 'A-Z' 'a-z')" in
        q) printf '已取消。\n'; exit 0 ;;
        1) pick_manual && break ;;
        2) sudo_prepare || continue; pick_from_list && break ;;
        *) err '输入无效，请重新选择。' ;;
    esac
done

# ---------- 2. 连接 + 校验 ----------
ALT_TRIED=0
NM_OK=0
OUT=""
while :; do
    sudo_prepare || exit 1
    hr
    say "正在连接 Wi-Fi：<$SSID> ..."
    if [ -z "$WPASS" ]; then
        OUT=$(srun nmcli dev wifi connect "$SSID" 2>&1)
        RC=$?
    else
        OUT=$(srun nmcli dev wifi connect "$SSID" password "$WPASS" 2>&1)
        RC=$?
    fi
    [ -n "$OUT" ] && printf '%s\n' "$OUT" | sed 's/^/  /'
    case "$OUT" in
        *'successfully activated'*) NM_OK=1 ;;
        *) NM_OK=0 ;;
    esac

    ONLINE=0
    if [ "$NM_OK" = 1 ]; then
        say '正在校验网络（ping www.baidu.com）...'
        printf '  正在等待网络就绪（最多 %d 秒）...\n' $((WAIT_MAX * WAIT_SEC))
        n=1
        while [ "$n" -le "$WAIT_MAX" ]; do
            if ping -c 2 -W 3 www.baidu.com >/dev/null 2>&1; then
                ONLINE=1
                break
            fi
            n=$((n + 1))
            if [ "$n" -le "$WAIT_MAX" ]; then
                printf '  第 %d 次未通，%d 秒后再试（%d/%d）...\n' $((n - 1)) "$WAIT_SEC" "$n" "$WAIT_MAX"
                sleep "$WAIT_SEC"
            fi
        done
    fi

    if [ "$NM_OK" = 1 ] && [ "$ONLINE" = 1 ]; then
        hr
        ok "Wi-Fi 连接成功：$SSID"
        DEV=$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2 == "wifi" { print $1; exit }')
        IP=$(nmcli -g IP4.ADDRESS dev show "$DEV" 2>/dev/null | head -1)
        [ -n "$IP" ] && printf '  机器人 IP：%s\n' "$IP"
        printf '  外网连通：ping www.baidu.com 正常\n'
        printf '\n  3 秒后自动关闭窗口。\n'
        sleep 3
        exit 0
    fi

    # 没连上：如果提示「找不到这个 SSID」，再扫一次找找相近的名字
    if [ "$ALT_TRIED" = 0 ]; then
        case "$OUT" in
            *'No network with SSID'*|*'not found'*)
                ALT=$(scan_lines | awk -F'\t' -v t="$SSID" '
                    $2 != "" && $2 != t && (index(t, $2) > 0 || index($2, t) > 0) { print $2; exit }
                ')
                if [ -n "$ALT" ]; then
                    printf '\n  没找到 '\''%s'\''，但附近扫到了相似的 Wi-Fi：'\''%s'\''\n' "$SSID" "$ALT"
                    ask_line "  改成连接 '$ALT' 吗？（y=改，其它键=不改）："
                    case "$(printf '%s' "$_ans" | tr 'A-Z' 'a-z')" in
                        y|yes) SSID="$ALT"; ALT_TRIED=1; continue ;;
                    esac
                fi
                ;;
        esac
    fi
    break
done

# ---------- 3. 失败原因 ----------
hr
err 'Wi-Fi 连接失败'
printf '  目标 Wi-Fi : <%s>\n' "$SSID"
if [ "$NM_OK" = 1 ]; then
    printf '  nmcli      : 已连上 Wi-Fi，但上不了外网\n'
else
    printf '  nmcli      : 连接未成功\n'
fi

printf '\n  nmcli 输出：\n'
if [ -z "$OUT" ]; then
    printf '    （无输出）\n'
else
    printf '%s\n' "$OUT" | sed 's/^/    /'
fi

printf '\n  可能原因：\n'
case "$OUT" in
    *'No network with SSID'*|*'not found'*)
        printf '    · 没找到这个 Wi-Fi：SSID 拼写 / 大小写不对，或不在覆盖范围内\n'
        printf '      （机器人通常只支持 2.4G，请确认路由器开了 2.4G 频段）\n' ;;
esac
case "$OUT" in
    *'Secrets were required'*|*'802-11-wireless-security'*)
        printf '    · 密码错误或加密方式不匹配\n' ;;
esac
if [ "$NM_OK" = 1 ]; then
    printf '    · Wi-Fi 已连上但 ping 不通：检查路由器本身是否联网\n'
    printf '      （酒店/公司网络常需要网页认证，机器人无法通过）\n'
    if ping -c 2 -W 3 223.5.5.5 >/dev/null 2>&1; then
        printf '    · ping IP 是通的，说明只是 DNS 解析失败\n'
    else
        printf '    · 机器人可能没拿到 IP 地址，检查路由器 DHCP\n'
    fi
fi

printf '\n  机器人当前网络状态：\n'
nmcli -t -f DEVICE,STATE,CONNECTION device status 2>/dev/null | sed 's/^/    /'

printf '\n按回车键关闭窗口...'
IFS= read -r _dummy
exit 1
