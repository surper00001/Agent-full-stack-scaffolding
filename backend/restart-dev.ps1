#Requires -Version 5.1
<#
.SYNOPSIS
  快速重启后端开发服务（uvicorn :8000）

.NOTES
  项目路径含空格时，uv run 会触发 trampoline 错误，故使用 .venv 内 python -m uvicorn。
  优先使用用户目录下的独立 uv（非 Conda Scripts 里的包装版）。
#>

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
if ($PSVersionTable.PSVersion.Major -ge 6) {
    $PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
}
try { chcp 65001 | Out-Null } catch { }

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:LC_ALL = 'C.UTF-8'
$env:LANG = 'zh_CN.UTF-8'

# Conda 的 SSL_CERT_DIR 常指向无效目录，会刷屏警告
if ($env:SSL_CERT_DIR -and -not (Test-Path -LiteralPath $env:SSL_CERT_DIR)) {
    Remove-Item Env:SSL_CERT_DIR -ErrorAction SilentlyContinue
}

$ErrorActionPreference = 'Stop'
$Port = 8000

$BackendRoot = $PSScriptRoot
if (-not $BackendRoot) {
    $BackendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
Set-Location -LiteralPath $BackendRoot

# 强制使用项目 .venv：从 PATH 移除 Conda，否则 uvicorn --reload 子进程会误用 Anaconda Python
$venvScripts = Join-Path $BackendRoot '.venv\Scripts'
$venvPython = Join-Path $venvScripts 'python.exe'
if (Test-Path -LiteralPath $venvScripts) {
    $env:VIRTUAL_ENV = Join-Path $BackendRoot '.venv'
    $cleanPath = ($env:PATH -split ';' | Where-Object {
            $_ -and
            ($_ -notmatch '(?i)\\Anaconda3\\|\\miniconda3?\\|\\conda\\|conda\\Scripts|conda\\Library')
        }) -join ';'
    $env:PATH = "$venvScripts;$cleanPath"
}

function Stop-ProcessOnPort {
    param([int]$ListenPort)

    $killed = @()

    # 先结束所有 uvicorn 开发进程（含 reload 父进程），避免 Conda Python 占坑
    try {
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -match 'uvicorn\s+src\.main:app' -or
                ($_.CommandLine -match 'multiprocessing\.spawn.*spawn_main' -and
                    $_.ExecutablePath -match '(?i)Anaconda3|miniconda|conda')
            } |
            ForEach-Object {
                $processId = [int]$_.ProcessId
                if ($processId -gt 0 -and $killed -notcontains $processId) {
                    Write-Host ('结束 uvicorn/Conda 子进程 PID {0}' -f $processId) -ForegroundColor Yellow
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                    $killed += $processId
                }
            }
    }
    catch { }

    try {
        $conns = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction Stop
        foreach ($c in $conns) {
            $processId = $c.OwningProcess
            if ($processId -and $processId -gt 0 -and $killed -notcontains $processId) {
                $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($proc) {
                    $msg = '结束占用端口 {0} 的进程: {1} (PID {2})' -f $ListenPort, $proc.ProcessName, $processId
                    Write-Host $msg -ForegroundColor Yellow
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                    $killed += $processId
                }
            }
        }
    }
    catch {
        $pattern = ":$ListenPort\s"
        $lines = netstat -ano | Select-String 'LISTENING' | Select-String $pattern
        foreach ($line in $lines) {
            if ($line.Line -match '\s+(\d+)\s*$') {
                $processId = [int]$Matches[1]
                if ($processId -gt 0 -and $killed -notcontains $processId) {
                    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    if ($proc) {
                        $msg = '结束占用端口 {0} 的进程: {1} (PID {2})' -f $ListenPort, $proc.ProcessName, $processId
                        Write-Host $msg -ForegroundColor Yellow
                        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                        $killed += $processId
                    }
                }
            }
        }
    }

    if ($killed.Count -eq 0) {
        Write-Host ('端口 {0} 当前无监听进程，跳过释放。' -f $ListenPort) -ForegroundColor DarkGray
    }
    else {
        Start-Sleep -Milliseconds 500
    }

    # 二次清理：确保端口上无残留 LISTEN（含 Conda reload 孤儿进程）
    for ($i = 0; $i -lt 5; $i++) {
        $listeners = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue
        if (-not $listeners) { break }
        foreach ($c in $listeners) {
            $processId = $c.OwningProcess
            if ($processId -gt 0) {
                Write-Host ('二次清理端口 {0} PID {1}' -f $ListenPort, $processId) -ForegroundColor Yellow
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Milliseconds 800
    }
}

function Get-StandaloneUv {
    $candidates = @(
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
    )
    foreach ($p in $candidates) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'Anaconda3|miniconda|conda') {
        return $cmd.Source
    }
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-VenvPython {
    $venvPython = Join-Path $BackendRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) { return $venvPython }
    return $null
}

function Ensure-ProjectVenv {
    $venvPython = Get-VenvPython
    if ($venvPython) { return $venvPython }

    $uvExe = Get-StandaloneUv
    if (-not $uvExe) {
        Write-Host '未找到 .venv，且系统无 uv，无法创建虚拟环境。' -ForegroundColor Red
        Write-Host '请执行: uv sync  或安装 https://docs.astral.sh/uv/' -ForegroundColor DarkGray
        exit 1
    }

    Write-Host '未检测到 .venv，正在执行 uv sync ...' -ForegroundColor Yellow
    & $uvExe sync
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $venvPython = Get-VenvPython
    if (-not $venvPython) {
        Write-Host 'uv sync 完成但仍未找到 .venv\Scripts\python.exe' -ForegroundColor Red
        exit 1
    }
    return $venvPython
}

Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  后端开发服务重启' -ForegroundColor Cyan
Write-Host ('  目录: {0}' -f $BackendRoot) -ForegroundColor Cyan
Write-Host ('  端口: {0}' -f $Port) -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host ('[1/3] 释放端口 {0} ...' -f $Port) -ForegroundColor Green
Stop-ProcessOnPort -ListenPort $Port

$pythonExe = Ensure-ProjectVenv
$uvExe = Get-StandaloneUv

Write-Host ''
Write-Host '[2/3] 同步依赖并校验 pdfplumber ...' -ForegroundColor Green
if ($uvExe) {
    & $uvExe sync
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
else {
    Write-Host '  未找到 uv，跳过 uv sync' -ForegroundColor DarkGray
}

Write-Host ('  使用 Python: {0}' -f $pythonExe) -ForegroundColor DarkGray
if ($pythonExe -match 'Anaconda3|miniconda|conda') {
    Write-Host '  错误: 检测到 Conda Python，请只用 backend\.venv' -ForegroundColor Red
    exit 1
}
& $pythonExe -c "import pdfplumber, fitz, docx; import sys; print('  依赖检查 OK |', sys.executable)"
if ($LASTEXITCODE -ne 0) {
    Write-Host '  pdfplumber 等依赖缺失，请确认使用 backend\.venv 而非 Conda 全局 Python' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '[3/3] 启动 uvicorn ...' -ForegroundColor Green
# Windows + Conda 基底 venv：--reload 会 spawn Anaconda 子进程（旧代码、缺依赖）
# 开发时改代码后请重新运行本脚本
$useReload = ($IsLinux -or $IsMacOS) -or ($env:OS -notmatch 'Windows')
if ($useReload) {
    $cmdLine = '{0} -m uvicorn src.main:app --reload --port {1}' -f $pythonExe, $Port
    Write-Host ('  命令: {0}' -f $cmdLine) -ForegroundColor DarkGray
    Write-Host ''
    & $pythonExe -m uvicorn src.main:app --reload --port $Port
}
else {
    $cmdLine = '{0} -m uvicorn src.main:app --port {1}' -f $pythonExe, $Port
    Write-Host ('  命令: {0}' -f $cmdLine) -ForegroundColor DarkGray
    Write-Host '  (Windows 已禁用 --reload，避免 Conda 子进程；改代码后请再运行本脚本)' -ForegroundColor DarkGray
    Write-Host ''
    & $pythonExe -m uvicorn src.main:app --port $Port
}