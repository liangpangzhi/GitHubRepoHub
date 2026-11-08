# 一键打包 GitHub Repo Hub 为单文件 exe（需已安装 Python 3.11+ 与 PySide6）
# 用法：在仓库根目录执行  powershell -ExecutionPolicy Bypass -File .\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$entry = Join-Path $root "github_repo_hub.py"
$icon = Join-Path $root "app.ico"

Write-Host "==> 检查依赖" -ForegroundColor Cyan
python -c "import PySide6, PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "正在安装 PySide6 与 PyInstaller ..." -ForegroundColor Yellow
    pip install PySide6 pyinstaller
}

Write-Host "==> 开始打包" -ForegroundColor Cyan
# 注意：所有路径均传绝对路径，否则 PyInstaller 在 CopyIcons 阶段可能因相对路径解析失败
python -m PyInstaller --noconfirm --onefile --windowed --clean `
    --name GitHubRepoHub `
    --icon $icon `
    --exclude-module tkinter `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtMultimedia `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $root "build") `
    --specpath $root `
    $entry

if ($LASTEXITCODE -eq 0) {
    $exe = Join-Path $root "dist\GitHubRepoHub.exe"
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 2)
    Write-Host "==> 打包完成：$exe ($size MB)" -ForegroundColor Green
} else {
    Write-Host "==> 打包失败，请检查上方日志" -ForegroundColor Red
    exit 1
}
