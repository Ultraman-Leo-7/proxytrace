# 取消开机自启（不会删除已采集的数据）。
$ErrorActionPreference = "Stop"

$startup = [Environment]::GetFolderPath('Startup')
$lnk     = Join-Path $startup "ProxyTrace.lnk"

if (Test-Path $lnk) {
    Remove-Item $lnk -Force
    Write-Host "已取消开机自启：" $lnk
} else {
    Write-Host "未找到开机自启快捷方式，无需取消。"
}
Write-Host "提示：若程序仍在后台运行，双击 停止.vbs 即可结束。"
