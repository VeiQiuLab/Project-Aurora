param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if ($Python) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        Write-Error "Explicit Python executable not found: $Python"
    }
    $Python = (Resolve-Path -LiteralPath $Python).Path
} else {
    $pythonCandidates = @()
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source) {
        $pythonCandidates += $pythonCommand.Source
    }
    $pythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"

    foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Python = $candidate
            break
        }
    }
}

if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Error "Full CPython 3.12 is required. Pass it explicitly with: .\build_exe.ps1 -Python C:\Path\To\python.exe"
}

& $Python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 3.12 is required for the Windows release build. Selected executable: $Python"
}

& $Python -c "import tkinter; import tkinter.ttk; import tkinter.filedialog; print('Tkinter OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python Tcl/Tk validation failed. Use a full Windows CPython 3.12 install, not a stripped runtime."
}

$releaseVersion = (& $Python -c "from modules.version import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $releaseVersion) {
    Write-Error "Unable to read VERSION from modules/version.py"
}
Write-Host "Building Project Aurora $releaseVersion with $Python"

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
