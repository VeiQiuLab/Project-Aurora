$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

foreach ($directory in @("data", "data\conversations", "data\memory", "config", "logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot $directory) | Out-Null
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Error "PyInstaller is not installed. Run: python -m pip install pyinstaller"
}

if (-not (Test-Path (Join-Path $projectRoot "assets\app.ico"))) {
    Write-Warning "assets\app.ico not found; building with the default application icon."
}

pyinstaller --noconfirm --clean "Project Aurora.spec"
Write-Host "Build complete: dist\Project Aurora\Project Aurora.exe"
