# ============================================================
#  一键让机器人连接 Wi-Fi（Windows 版）
#
#  用法：双击同目录的「一键连接机器人WiFi.cmd」
#  （本文件名保持 ASCII，避免 cmd 在 chcp 65001 之后读中文文件名出问题）
#
#  机器人端不装任何东西、不改任何配置：
#    ssh 登录后把 robot-wifi-remote.sh 临时放到机器人 /tmp 执行，跑完立即删除，
#    执行的命令和 mac 版完全一致（nmcli 扫描 / nmcli 连接 / ping 校验）。
#
#  可改参数：
#    -RobotIp        机器人地址，默认 192.168.90.1
#    -SshUser        登录账号，默认 robot
#    -WifiPassword   回车默认使用的 Wi-Fi 密码，默认 AI2Rocks!
# ============================================================

param(
    [string]$RobotIp      = '192.168.90.1',
    [string]$SshUser      = 'robot',
    [string]$WifiPassword = 'AI2Rocks!'
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-Say {
    param([string]$m)
    Write-Host ''
    Write-Host "▶ $m" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$m)
    Write-Host "✔ $m" -ForegroundColor Green
}

function Write-Warn {
    param([string]$m)
    Write-Host "! $m" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$m)
    Write-Host "✘ $m" -ForegroundColor Red
}

function Write-Hr {
    Write-Host ('-' * 60)
}

function Wait-Close {
    param([int]$Code)
    Write-Host ''
    Read-Host '按回车键关闭窗口...' | Out-Null
    exit $Code
}

# 找 Windows 自带的可执行文件（PATH 里没有时去 System32\OpenSSH 找）
function Find-Exe {
    param([string]$Name)
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = Join-Path $env:WINDIR ('System32\OpenSSH\' + $Name)
    if (Test-Path $p) { return $p }
    return $null
}

# 把值安全地塞进 bash 单引号里
function Escape-BashSingle {
    param([string]$s)
    return $s.Replace("'", "'\''")
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }

try {
    Write-Host ('=' * 60)
    Write-Host '               机器人 Wi-Fi 连接助手（Windows）'
    Write-Host "               设备：$SshUser@$RobotIp"
    Write-Host ('=' * 60)

    # ---------- 0. 检查依赖 ----------
    $sshExe  = Find-Exe 'ssh.exe'
    $keyExe  = Find-Exe 'ssh-keygen.exe'
    if (-not $sshExe -or -not $keyExe) {
        Write-Err '找不到 Windows 自带的 OpenSSH 客户端（ssh.exe / ssh-keygen.exe）'
        Write-Host '  用管理员身份打开 PowerShell，执行下面这条，然后重新运行本脚本：'
        Write-Host '    Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'
        Wait-Close 1
    }

    # ---------- 1. 清除 key 缓存 ----------
    Write-Hr
    Write-Say '清除缓存 ...'
    & $keyExe -R $RobotIp 2>&1 | Out-Null
    Write-Ok "缓存已清除：$RobotIp"

    # ---------- 2. 先确认电脑和机器人之间是通的 ----------
    Write-Hr
    Write-Say "检查设备连接 ... ping $RobotIp"
    $pingOk = $false
    try { $pingOk = [bool](Test-Connection -ComputerName $RobotIp -Count 2 -Quiet -ErrorAction SilentlyContinue) } catch { $pingOk = $false }
    if ($pingOk) {
        Write-Ok "设备可达（$RobotIp 能 ping 通）"
    } else {
        Write-Warn "ping $RobotIp 不通"
        $portOk = $false
        try {
            $portOk = [bool](Test-NetConnection -ComputerName $RobotIp -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue)
        } catch { $portOk = $false }
        if ($portOk) {
            Write-Warn '但 22 端口（ssh）可达，继续尝试连接 ...'
        } else {
            Write-Err '连接失败：是否没有连接到设备？'
            Write-Host ''
            Write-Host '请检查：'
            Write-Host '  1) 电脑是否已连上机器人（机器人热点 / 同一局域网 / 网线直连）'
            Write-Host "  2) 机器人地址是否正确：$RobotIp"
            Write-Host '  3) 机器人是否已开机'
            Wait-Close 1
        }
    }

    # ---------- 3. 组装要发到机器人上执行的临时脚本 ----------
    $shFile = Join-Path $scriptDir 'robot-wifi-remote.sh'
    if (-not (Test-Path $shFile)) {
        Write-Err "找不到 robot-wifi-remote.sh，请确认它和本脚本放在同一个文件夹：$scriptDir"
        Wait-Close 1
    }
    $remoteSh = Get-Content -Raw -Encoding UTF8 $shFile
    $remoteSh = $remoteSh.Replace('__ROBOT_IP__', $RobotIp)
    $remoteSh = $remoteSh.Replace('__DEFAULT_WIFI_PASS__', (Escape-BashSingle $WifiPassword))
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteSh))

    # 机器人端：落到 /tmp -> 执行 -> 退出时删除（base64 里没有特殊字符，不会破坏命令行）
    $tpl = @'
S=$(mktemp /tmp/rwifi-XXXXXX.sh); trap 'rm -f $S' EXIT; echo {0} | base64 -d > $S; bash $S
'@
    $remoteCmd = $tpl.Replace('{0}', $b64).Trim()

    # ---------- 4. 连接机器人（这里会提示输入机器人密码） ----------
    Write-Hr
    Write-Say "连接设备中 ... $SshUser@$RobotIp"
    Write-Host '  （提示 password 时输入机器人密码；进入机器人后 sudo 会再问一次，同样输入它）'
    & $sshExe -t -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o NumberOfPasswordPrompts=3 "$SshUser@$RobotIp" $remoteCmd
    $rc = $LASTEXITCODE

    if ($rc -eq 1) {
        # 远端已经提示过失败原因并等过回车了
        exit 1
    }
    if ($rc -ne 0) {
        Write-Host ''
        Write-Err "ssh 连接失败（退出码 $rc）"
        Write-Host '  请确认：1) 机器人密码是否正确  2) 设备是否在线  3) 是否已在机器人热点/局域网里'
        Wait-Close $rc
    }
    exit 0
}
catch {
    Write-Host ''
    Write-Err "脚本出错：$($_.Exception.Message)"
    Wait-Close 1
}
