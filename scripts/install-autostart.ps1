# 在「开始 - 启动」文件夹创建快捷方式，实现开机登录后自动后台启动
# ProxyTrace（采集 + 网页面板）。本脚本只设置自启，不会立即启动。
$ErrorActionPreference = "Stop"

$projDir = Split-Path -Parent $PSScriptRoot
$vbs     = Join-Path $projDir "启动.vbs"
$startup = [Environment]::GetFolderPath('Startup')
$lnk     = Join-Path $startup "ProxyTrace.lnk"

if (-not (Test-Path $vbs)) { throw "找不到 $vbs" }

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath       = $vbs
$sc.WorkingDirectory = $projDir
$sc.Description      = "ProxyTrace 代理流量记账（开机自启）"
$sc.Save()

Write-Host "已设置开机自启：" $lnk
Write-Host "下次登录系统时会自动在后台启动采集与网页面板。"
Write-Host "如需取消，运行 scripts\uninstall-autostart.ps1。"
