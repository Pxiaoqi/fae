#!/bin/bash
# ============================================================
# 一键让机器人连接 Wi-Fi（双击运行）
#
# 流程：
#   1. 清除本机 SSH key 缓存（ssh-keygen -R 192.168.90.1）
#   2. 连接机器人（ssh robot@192.168.90.1），失败提示"是否没有连接到设备"
#   3. 选择：手动输入 Wi-Fi / 扫描并选择 Wi-Fi
#   4. 机器人端执行 sudo nmcli dev wifi connect ... 连接
#   5. 监听是否真的联网（ping www.baidu.com）
#   6. 成功自动退出；失败打印失败原因
#
# 用法（默认值如下，均可改）：
#   双击运行        -> 机器人 192.168.90.1
#   ./一键连接机器人WiFi.command 192.168.90.1
#   可用环境变量覆盖：SSH_USER / SSH_PASS / DEFAULT_WIFI_PASS
# ============================================================

export ROBOT_IP="${1:-192.168.90.1}"
export SSH_USER="${SSH_USER:-robot}"
export SSH_PASS="${SSH_PASS:-robot}"
# 机器人 Wi-Fi 常用密码（来自《北京智魔方机器人信息表》），回车即用
export DEFAULT_WIFI_PASS="${DEFAULT_WIFI_PASS:-AI2Rocks!}"

# expect 脚本要读键盘输入，所以必须放到临时文件里执行（脚本不能从 stdin 读）
TMP_EXP="$(mktemp -t robot-wifi)"
if [ -z "$TMP_EXP" ] || [ ! -f "$TMP_EXP" ]; then
  echo "[失败] 无法创建临时文件"
  read -r -p "按回车键退出..."
  exit 1
fi
trap 'rm -f "$TMP_EXP"' EXIT INT TERM HUP

cat > "$TMP_EXP" <<'EXP_EOF'
# ============================================================
#  机器人 Wi-Fi 连接助手（由 一键连接机器人WiFi.command 调用）
# ============================================================

set HOST   $env(ROBOT_IP)
set USER   $env(SSH_USER)
set PASS   $env(SSH_PASS)
set WPASS  $env(DEFAULT_WIFI_PASS)
set MARK   "___DONE___"
set CMDNO  0
set WIFI_DEV ""
set ::timeout 30

# 远端命令输出全部由本脚本自己排版打印
log_user 0

set ESC     [format %c 27]
set C_CYAN  [format {%s[36m} $ESC]
set C_GREEN [format {%s[32m} $ESC]
set C_RED   [format {%s[31m} $ESC]
set C_YEL   [format {%s[33m} $ESC]
set C_RST   [format {%s[0m}  $ESC]

proc say  {m} { puts "\n$::C_CYAN▶ $m$::C_RST" ; flush stdout }
proc ok   {m} { puts "$::C_GREEN✔ $m$::C_RST" ; flush stdout }
proc err  {m} { puts "$::C_RED✘ $m$::C_RST" ; flush stdout }
proc warn {m} { puts "$::C_YEL! $m$::C_RST" ; flush stdout }
proc hr   {}  { puts "------------------------------------------------------------" }

# ---------------- 输入辅助 ----------------
proc ask {prompt} {
    send_user "$prompt"
    flush stdout
    set line ""
    if {[catch { gets stdin line } n]} { set n 0 }
    if {$n < 0} {
        # 标准输入被关掉（窗口关了）
        puts ""
        bye 0
    }
    return [string trim $line]
}

proc ask_secret {prompt} {
    send_user "$prompt"
    flush stdout
    tty_echo -echo
    set line ""
    if {[catch { gets stdin line } n]} { set n 0 }
    tty_echo echo
    send_user "\n"
    if {$n < 0} { bye 0 }
    return [string trim $line]
}

# 关闭/恢复终端回显（stdin 不是终端时会失败，忽略即可）
proc tty_echo {onoff} {
    catch { stty $onoff }
}

# shell 单引号转义：把 ' 变成 '\''
proc shq {s} {
    return "'[string map {' {'\\''}} $s]'"
}

# 去掉 ANSI 颜色/控制转义（nmcli、shell 在某些终端下会带上 \033[0m 之类）
proc strip_ansi {s} {
    set s [regsub -all {\x1b\[[0-9;?]*[ -/]*[@-~]} $s ""]
    set s [regsub -all {\x1b[()][A-Za-z0-9]} $s ""]
    return $s
}

# 单行文本清洗：去 ANSI、去控制字符、去首尾空白（用于 SSID / 密码）
proc clean_text {s} {
    set s [strip_ansi $s]
    regsub -all {[\x00-\x1f\x7f]} $s "" s
    return [string trim $s]
}

# 去掉远端回显的命令行和结束标记
proc clean_out {cmd s} {
    set s [strip_ansi $s]
    # 命令回显那行（含前面的 shell 提示符）整行删掉
    set idx [string first $cmd $s]
    if {$idx >= 0} {
        set nl [string first "\n" $s $idx]
        if {$nl >= 0} { set s [string range $s [expr {$nl + 1}] end] }
    }
    set res {}
    foreach l [split $s "\n"] {
        if {[regexp {___D[0-9]*ONE___} $l]} { continue }
        lappend res [string trimright $l "\r"]
    }
    while {[llength $res] > 0 && [string trim [lindex $res end]] eq ""} {
        set res [lrange $res 0 end-1]
    }
    return [join $res "\n"]
}

# 在机器人上执行一条命令，返回 {状态 输出}
# 状态：ok / timeout / eof
proc run {cmd {tmo 60}} {
    global spawn_id
    # 每条命令用独立标记，避免上一条命令的残留标记被误判成这条的结果
    incr ::CMDNO
    set mk "___D${::CMDNO}ONE___"
    set out ""
    set status "ok"
    # 回显里写成 ___D1""ONE___，真正输出的标记是 ___D1ONE___，不会提前误匹配
    if {[catch { send -- "$cmd; echo ___D${::CMDNO}\"\"ONE___\r" }]} {
        # 会话已经断了
        return [list "eof" ""]
    }
    set old $::timeout
    set ::timeout $tmo
    set failed [catch {
        expect {
            -nocase -re {\[sudo\] password for [^\r\n]*:} {
                append out $expect_out(buffer)
                send -- "$::PASS\r"
                exp_continue
            }
            -nocase -re {password for [^\r\n]*:} {
                append out $expect_out(buffer)
                send -- "$::PASS\r"
                exp_continue
            }
            -ex $mk { append out $expect_out(buffer) }
            timeout {
                append out $expect_out(buffer)
                set status "timeout"
            }
            eof {
                append out $expect_out(buffer)
                set status "eof"
            }
        }
    }]
    if {$failed} { set status "eof" }
    set ::timeout $old
    return [list $status [clean_out $cmd $out]]
}

# 解析 nmcli -t 的一行（\: 转义成冒号）
proc tf {line} {
    set fields {}
    set cur ""
    set esc 0
    foreach ch [split $line ""] {
        if {$esc} { append cur $ch ; set esc 0 ; continue }
        if {$ch eq "\\"} { set esc 1 ; continue }
        if {$ch eq ":"} { lappend fields $cur ; set cur "" ; continue }
        append cur $ch
    }
    lappend fields $cur
    return $fields
}

# 解析 Wi-Fi 列表，按信号强度去重排序，返回 {{ssid sig sec} ...}
proc parse_wifi {raw} {
    set best [dict create]
    foreach line [split $raw "\n"] {
        set line [string trim $line]
        if {$line eq ""} { continue }
        set f [tf $line]
        if {[llength $f] < 3} { continue }
        set ssid [clean_text [lindex $f 0]]
        set sig  [clean_text [lindex $f 1]]
        set sec  [clean_text [lindex $f 2]]
        if {$ssid eq "" || $ssid eq "--"} { continue }
        if {![string is integer -strict $sig]} { set sig 0 }
        if {[dict exists $best $ssid]} {
            if {$sig > [lindex [dict get $best $ssid] 0]} {
                dict set best $ssid [list $sig $sec]
            }
        } else {
            dict set best $ssid [list $sig $sec]
        }
    }
    set tmp {}
    dict for {ssid v} $best {
        lappend tmp [list $ssid [lindex $v 0] [lindex $v 1]]
    }
    return [lsort -integer -decreasing -index 1 $tmp]
}

# 询问 Wi-Fi 密码（回车用默认密码，输入 - 表示开放网络）
proc ask_wifi_pass {ssid} {
    set p [ask_secret "请输入 $ssid 的密码（回车=默认 $::WPASS，输入 - 表示无密码）："]
    set p [clean_text $p]
    if {$p eq "-"} { return "" }
    if {$p eq ""} { return $::WPASS }
    return $p
}

# 连上以后还要等网络真的能用：DHCP 拿地址、路由生效都要时间
proc verify_online {max_try interval} {
    for {set i 1} {$i <= $max_try} {incr i} {
        if {$i == 1} {
            puts "  正在等待网络就绪（最多 [expr {$max_try * $interval}] 秒）..."
        } else {
            puts "  第 [expr {$i - 1}] 次未通，[expr {$interval}] 秒后再试（$i/$max_try）..."
        }
        set pr [run "ping -c 2 -W 3 www.baidu.com; echo PINGEXIT=\$?" 40]
        if {[lindex $pr 0] eq "eof"} { return "eof" }
        if {[regexp {PINGEXIT=0} [lindex $pr 1]]} { return "ok" }
        if {$i < $max_try} { after [expr {$interval * 1000}] }
    }
    return "fail"
}

# 连不上时再扫一遍，看是不是 SSID 多/少了字符（例如混进了转义残留）
proc suggest_ssid {failed} {
    set rr [run "sudo nmcli -t -f SSID dev wifi list" 60]
    if {[lindex $rr 0] ne "ok"} { return "" }
    foreach l [split [lindex $rr 1] "\n"] {
        set n [clean_text [lindex [tf $l] 0]]
        if {[string length $n] < 4} { continue }
        if {$n eq $failed} { continue }
        if {[string first $n $failed] >= 0 || [string first $failed $n] >= 0} { return $n }
    }
    return ""
}

# 结束：关闭 ssh 会话并退出
proc bye {code} {
    global spawn_id
    catch { send -- "exit\r" }
    set ::timeout 5
    catch { expect { eof {} timeout {} } }
    # 兜底：确保 ssh 进程不会残留在后台
    catch { close -i $spawn_id }
    exit $code
}

proc pause_exit {code} {
    puts ""
    catch { ask "按回车键关闭窗口..." }
    bye $code
}

# ---------------- 登录 ----------------
# ---------------- 连接设备前的本机检查 ----------------
# 先 ping 一下机器人：不通就说明电脑和机器人之间没通
proc net_ping {host} {
    if {[catch { exec /bin/sh -c "ping -c 2 -t 3 '$host' >/dev/null 2>&1" }]} { return 0 }
    return 1
}

# 再看 22 端口（有些网络禁 ICMP，但 ssh 其实是通的，避免误判）
proc net_port {host port} {
    if {[catch { exec /bin/sh -c "nc -z -G 3 '$host' $port >/dev/null 2>&1" }]} { return 0 }
    return 1
}

# 密码通过后，等 shell 真正起来再发命令
# （OpenSSH 读密码时会用 TCSAFLUSH 丢掉当时已排队的输入，命令要等到之后再发）
proc wait_shell {max_wait} {
    global spawn_id
    set deadline [expr {[clock seconds] + $max_wait}]
    while {1} {
        after 2000
        if {[catch { send -- "echo ___D\"\"ONE___\r" }]} { return "eof" }
        set old $::timeout
        set ::timeout 3
        set r "wait"
        catch {
            expect {
                -ex $::MARK { set r "ok" }
                -nocase -re {password:} { set r "auth" }
                -nocase -re {permission denied|authentication failed} { set r "auth" }
                timeout { }
                eof { set r "eof" }
            }
        }
        set ::timeout $old
        if {$r ne "wait"} { return $r }
        if {[clock seconds] >= $deadline} { return "timeout" }
    }
}

proc login_once {} {
    global spawn_id
    set res "unknown"
    set ::timeout 25
    spawn ssh -t -o ConnectTimeout=10 -o NumberOfPasswordPrompts=1 "$::USER@$::HOST"
    expect {
        -nocase -re {are you sure you want to continue connecting} {
            send -- "yes\r"
            exp_continue
        }
        -nocase -re {password:\s*$} {
            send -- "$::PASS\r"
            set res [wait_shell 25]
        }
        -ex $::MARK { set res "ok" }
        -nocase -re {permission denied|authentication failed} { set res "auth" }
        -nocase -re {host key verification failed|remote host identification has changed} { set res "hostkey" }
        -nocase -re {connection refused|connection timed out|no route to host|network is unreachable|could not resolve|connection closed|operation timed out} { set res "unreachable" }
        timeout {
            # 没等到密码提示就要超时：可能本来就是免密登录，已经进 shell 了
            if {[regexp {[\$#] $} $expect_out(buffer)]} {
                set res [wait_shell 10]
            } else {
                set res "timeout"
            }
        }
        eof { set res "eof" }
    }
    return $res
}

# ---------------- 扫描并选择 Wi-Fi ----------------
proc scan_and_pick {} {
    while {1} {
        say "wifi搜索中 ..."
        set rr [run "sudo nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list" 120]
        if {[lindex $rr 0] eq "eof"} {
            err "与机器人的连接已断开。"
            bye 1
        }
        set wifi_list [parse_wifi [lindex $rr 1]]
        if {[llength $wifi_list] == 0} {
            err "没有扫描到 Wi-Fi。"
            puts "  可能原因：网卡未启用 / 离路由器太远 / nmcli 不可用"
            set a [string tolower [ask "按 r 重新扫描，按 m 手动输入，按 q 退出："]]
            if {$a eq "m"} { return "" }
            if {$a eq "q"} { puts "已取消。"; bye 0 }
            continue
        }
        puts ""
        puts "  编号  Wi-Fi 名称                        信号    加密"
        puts "  ----  --------------------------------  ------  ------------"
        set i 0
        foreach item $wifi_list {
            incr i
            puts [format "  %4d  %-32s  %4s%%  %s" \
                $i [string range [lindex $item 0] 0 31] [lindex $item 1] [lindex $item 2]]
        }
        puts ""
        set pick [string trim [ask "请输入要连接的 Wi-Fi 编号（r=重新扫描，m=手动输入，q=退出）："]]
        set low [string tolower $pick]
        if {$low eq "r"} { continue }
        if {$low eq "m"} { return "" }
        if {$low eq "q"} { puts "已取消。"; bye 0 }
        if {![string is integer -strict $pick] || $pick < 1 || $pick > [llength $wifi_list]} {
            err "输入无效，请重新输入。"
            continue
        }
        set item [lindex $wifi_list [expr {$pick - 1}]]
        set ssid [lindex $item 0]
        set sec  [lindex $item 2]
        if {[string match -nocase "*WPA*" $sec] || [string match -nocase "*WEP*" $sec] || [string match -nocase "*802.1X*" $sec]} {
            set pwd [ask_wifi_pass $ssid]
        } else {
            puts "该 Wi-Fi 是开放网络（无加密），直接连接。"
            set pwd ""
        }
        return [list $ssid $pwd]
    }
}

# ============================================================
#                          主流程
# ============================================================
puts "============================================================"
puts "               机器人 Wi-Fi 连接助手"
puts "               设备：$USER@$HOST"
puts "============================================================"

# ---------- 1. 清除 key 缓存 ----------
hr
say "清除缓存 ..."
if {[catch { spawn sh -c "mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keygen -R $HOST" } e]} {
    warn "清除缓存失败：$e （忽略，继续）"
} else {
    expect { eof {} timeout {} }
    ok "缓存已清除：$HOST"
}

# ---------- 2. 先确认电脑和机器人之间是通的 ----------
hr
say "检查设备连接 ... ping $HOST"
if {[net_ping $HOST]} {
    ok "设备可达（$HOST 能 ping 通）"
} else {
    warn "ping $HOST 不通"
    if {[net_port $HOST 22]} {
        warn "但 22 端口（ssh）可达，继续尝试连接 ..."
    } else {
        err "连接失败：是否没有连接到设备？"
        puts ""
        puts "请检查："
        puts "  1) 电脑是否已连上机器人（机器人热点 / 同一局域网 / 网线直连）"
        puts "  2) 机器人地址是否正确：$HOST"
        puts "  3) 机器人是否已开机"
        pause_exit 1
    }
}

# ---------- 3. 连接机器人 ----------
hr
say "连接设备中 ... $USER@$HOST"
set r [login_once]
set tries 1
while {$r eq "auth" && $tries < 3} {
    err "登录密码错误（第 $tries 次）"
    set PASS [ask_secret "请重新输入机器人密码（$USER）："]
    incr tries
    set r [login_once]
}

if {$r ne "ok"} {
    switch -- $r {
        auth      { err "登录失败：账号或密码不正确（$USER）" }
        hostkey   { err "登录失败：SSH 主机密钥校验不通过" }
        default   {
            err "连接失败：是否没有连接到设备？"
            puts ""
            puts "请检查："
            puts "  1) 电脑是否已连上机器人（机器人热点 / 同一局域网 / 网线直连）"
            puts "  2) 机器人地址是否正确：$HOST"
            puts "  3) 机器人是否已开机、SSH 服务是否正常"
        }
    }
    pause_exit 1
}
ok "已连接到设备 $USER@$HOST"

# 找无线网卡名（仅用于后面显示状态）
set dr [run "nmcli -t -f DEVICE,TYPE device status" 25]
foreach l [split [lindex $dr 1] "\n"] {
    set f [tf [string trim $l]]
    if {[llength $f] >= 2 && [lindex $f 1] eq "wifi"} {
        set WIFI_DEV [lindex $f 0]
        break
    }
}
if {$WIFI_DEV ne ""} { puts "  无线网卡：$WIFI_DEV" }

# ---------- 4. 选择连接方式 ----------
set ssid ""
set pwd  ""
while {1} {
    hr
    puts "请选择 Wi-Fi 连接方式："
    puts "  1) 手动输入 Wi-Fi 名称和密码"
    puts "  2) 扫描并选择附近的 Wi-Fi"
    puts "  q) 退出"
    set sel [string tolower [ask "请输入 1 / 2 / q：" ]]
    if {$sel eq "q"} { puts "已取消。"; bye 0 }
    if {$sel eq "1"} {
        set ssid [clean_text [ask "请输入 Wi-Fi 名称（SSID）："]]
        if {[string trim $ssid] eq ""} { err "SSID 不能为空" ; continue }
        set pwd [ask_wifi_pass $ssid]
        break
    }
    if {$sel eq "2"} {
        set picked [scan_and_pick]
        if {$picked eq ""} { continue }
        set ssid [lindex $picked 0]
        set pwd  [lindex $picked 1]
        break
    }
    err "输入无效，请重新选择。"
}

# ---------- 5. 连接 Wi-Fi ----------
set nm_ok 0
set ping_ok 0
set ip_ok 0
set cout ""
set alt_tried 0

while {1} {
    hr
    say "正在连接 Wi-Fi：<$ssid> ..."
    if {[string trim $pwd] eq ""} {
        set cmd "sudo nmcli dev wifi connect [shq $ssid]"
    } else {
        set cmd "sudo nmcli dev wifi connect [shq $ssid] password [shq $pwd]"
    }
    set cr [run $cmd 150]
    set cstat [lindex $cr 0]
    set cout  [string trim [lindex $cr 1]]
    if {$cout ne ""} { foreach l [split $cout "\n"] { puts "  $l" } }
    if {$cstat eq "timeout"} { warn "nmcli 执行超时，继续校验网络 ..." }
    if {$cstat eq "eof"} { warn "连接过程中 SSH 断了，机器人可能正在切换网络" }

    set nm_ok [regexp -nocase {successfully activated} $cout]

    # SSH 中途断了：等机器人（热点）回来确认结果
    if {$cstat eq "eof" && !$nm_ok} {
        warn "与机器人的连接断开了，等 8 秒后重连确认结果 ..."
        after 8000
        if {[login_once] eq "ok"} {
            ok "已重新连上设备"
            set sr [run "nmcli -t -f DEVICE,STATE,CONNECTION device status" 25]
            if {$WIFI_DEV ne ""} {
                foreach l [split [lindex $sr 1] "\n"] {
                    if {[string first "${WIFI_DEV}:connected" [string trim $l]] >= 0} { set nm_ok 1 }
                }
            }
        } else {
            err "重连设备失败：无法确认 Wi-Fi 是否连上"
            puts "  机器人可能已连上新 Wi-Fi，但热点还在恢复中。"
            puts "  请等 10 秒后再运行一次本脚本，或用机器人屏幕确认网络状态。"
            pause_exit 1
        }
    }

    if {$nm_ok} {
        # ---------- 6. 校验网络（ping 百度） ----------
        say "正在校验网络（ping www.baidu.com）..."
        set vres [verify_online 8 5]
        if {$vres eq "eof"} {
            warn "校验时连接又断了，等 8 秒后重连再校验 ..."
            after 8000
            if {[login_once] eq "ok"} { set vres [verify_online 3 3] }
        }
        if {$vres eq "ok"} {
            set ping_ok 1
        } else {
            # 域名不通再试纯 IP，用来区分「没网」和「只是 DNS 坏了」
            set pr2 [run "ping -c 2 -W 3 223.5.5.5; echo PINGEXIT=\$?" 40]
            set ip_ok [regexp {PINGEXIT=0} [lindex $pr2 1]]
        }
        break
    }

    # 没连上：如果提示「找不到这个 SSID」，再扫一次找找相近的名字
    if {!$alt_tried && [regexp -nocase {no network with ssid|not found} $cout]} {
        set alt [suggest_ssid $ssid]
        if {$alt ne ""} {
            puts ""
            puts "  没找到 '$ssid'，但附近扫到了相似的 Wi-Fi：'$alt'"
            set yn [string tolower [ask "  改成连接 '$alt' 吗？（y=改，其它键=不改）："]]
            if {$yn eq "y" || $yn eq "yes"} {
                set ssid $alt
                set alt_tried 1
                continue
            }
        }
    }
    break
}

# ---------- 7. 结果 ----------
if {$nm_ok && $ping_ok} {
    hr
    ok "Wi-Fi 连接成功：$ssid"
    set ipr [run "nmcli -t -f IP4.ADDRESS device show $WIFI_DEV" 25]
    set iplines {}
    foreach l [split [lindex $ipr 1] "\n"] {
        set l [string trim $l]
        if {$l eq ""} { continue }
        if {[regexp {^[^:]+:(.*)$} $l -> ip]} { lappend iplines $ip }
    }
    if {[llength $iplines] > 0} { puts "  机器人 IP：$iplines" }
    puts "  外网连通：ping www.baidu.com 正常"
    puts ""
    puts "  3 秒后自动关闭窗口。"
    after 3000
    bye 0
}

hr
err "Wi-Fi 连接失败"
puts "  目标 Wi-Fi : <$ssid>"
if {!$nm_ok} {
    # 打印 SSID 的真实字节，便于排查混进转义字符的情况
    binary scan $ssid H* sshex
    puts "  SSID 字节  : $sshex"
}
if {$nm_ok} {
    puts "  nmcli      : 已连上 Wi-Fi，但上不了外网"
} else {
    puts "  nmcli      : 连接未成功"
}

puts ""
puts "  nmcli 输出："
if {$cout eq ""} {
    puts "    （无输出）"
} else {
    foreach l [split $cout "\n"] { puts "    $l" }
}

puts ""
puts "  可能原因："
if {[regexp -nocase {no network with ssid|not found|secrets were required|802-11-wireless-security} $cout]} {
    if {[regexp -nocase {no network with ssid|not found} $cout]} {
        puts "    · 没找到这个 Wi-Fi：SSID 拼写 / 大小写不对，或不在覆盖范围内"
        puts "      （机器人通常只支持 2.4G，请确认路由器开了 2.4G 频段）"
    }
    if {[regexp -nocase {secrets were required|802-11-wireless-security} $cout]} {
        puts "    · 密码错误或加密方式不匹配"
    }
}
if {$nm_ok} {
    puts "    · Wi-Fi 已连上但 ping 不通：检查路由器本身是否联网"
    puts "      （酒店/公司网络常需要网页认证，机器人无法通过）"
    if {$ip_ok} {
        puts "    · ping IP 是通的，说明只是 DNS 解析失败"
    } else {
        puts "    · 机器人可能没拿到 IP 地址，检查路由器 DHCP"
    }
}
if {[regexp -nocase {not authorized|permission denied|incorrect password} $cout]} {
    puts "    · 权限问题：sudo 密码可能不对（当前使用 robot 的密码）"
}

set st [run "nmcli -t -f DEVICE,STATE,CONNECTION device status" 25]
puts ""
puts "  机器人当前网络状态："
set any 0
foreach l [split [lindex $st 1] "\n"] {
    set l [string trim $l]
    if {$l eq ""} { continue }
    puts "    $l"
    set any 1
}
if {!$any} { puts "    （取不到状态）" }

pause_exit 1
EXP_EOF

/usr/bin/expect "$TMP_EXP"
exit $?
