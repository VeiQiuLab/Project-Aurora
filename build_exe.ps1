param(
    [string]$Python = "C:\Python312\python.exe"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Full CPython 3.12 is required. Install Python 3.12 for Windows with Tcl/Tk, then rerun: .\build_exe.ps1 -Python C:\Path\To\python.exe"
}

& $Python -c "import tkinter; import tkinter.ttk; import tkinter.filedialog; print('Tkinter OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python Tcl/Tk validation failed. Use a full Windows CPython 3.12 install, not a stripped runtime."
}

& $Python -m PyInstaller --version | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller is not installed in this Python environment. Run: & '$Python' -m pip install pyinstaller"
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "assets"))) {
    Write-Error "Missing release resource directory: assets"
}

$ffmpegPath = Join-Path $projectRoot "tools\ffmpeg.exe"
if (-not (Test-Path -LiteralPath $ffmpegPath)) {
    Write-Error "Missing bundled FFmpeg: tools\ffmpeg.exe"
}

& $Python -m PyInstaller --noconfirm --clean "Project Aurora.spec"
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed."
}

$distRoot = Join-Path $projectRoot "dist\Aurora"
if (-not (Test-Path -LiteralPath (Join-Path $distRoot "Aurora.exe"))) {
    Write-Error "Build output missing: dist\Aurora\Aurora.exe"
}

Copy-Item -LiteralPath (Join-Path $projectRoot "assets") -Destination (Join-Path $distRoot "assets") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "tools") -Destination (Join-Path $distRoot "tools") -Recurse -Force

foreach ($required in @("Aurora.exe", "_internal", "assets", "tools\ffmpeg.exe")) {
    $path = Join-Path $distRoot $required
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Error "Release output check failed: dist\Aurora\$required"
    }
}

Write-Host "Build complete: dist\Aurora\Aurora.exe"
