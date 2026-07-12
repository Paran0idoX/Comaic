$ErrorActionPreference = "Stop"

# PowerShell 只作为便捷入口；前后端进程、热重载和清理由 start.py 统一管理。
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($null -eq $python) {
    Write-Error "未找到 python.exe，请先安装 Python 或 Conda。"
    exit 1
}

& $python.Source (Join-Path $PSScriptRoot "start.py")
exit $LASTEXITCODE
