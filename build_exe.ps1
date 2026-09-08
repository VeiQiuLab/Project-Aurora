param(
    [string]$Python = "",
    [switch]$FullVoice,
    [string]$VoiceCodecOverlay = "build\voice-codec-overlay"
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

& $Python -c "import tkinter; import tkinter.ttk; import tkinter.filedialog; t = tkinter.Tcl(); print('Tkinter OK', t.eval('info patchlevel'))"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python Tcl/Tk validation failed. Use a full Windows CPython 3.12 install, not a stripped runtime."
}

& $Python -c "import customtkinter; print('CustomTkinter OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "CustomTkinter is not installed in the selected build environment."
}

$releaseVersion = (& $Python -c "from modules.version import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $releaseVersion) {
    Write-Error "Unable to read VERSION from modules/version.py"
}
Write-Host "Building Project Aurora $releaseVersion with $Python"

if ($FullVoice) {
    if (-not (Test-Path -LiteralPath (Join-Path $VoiceCodecOverlay 'overlay-integrity.json'))) {
        Write-Error "Prepare the locked LGPL codec overlay before building Full Voice. See docs/VOICE_RUNTIME_DISTRIBUTION.md."
    }
    $voicePolicy = Join-Path $projectRoot "config\voice_runtime_build.json"
    $voiceValidator = Join-Path $projectRoot "scripts\validate_voice_runtime.py"
    & $Python $voiceValidator --policy $voicePolicy --validate-environment
    if ($LASTEXITCODE -ne 0) {
        Write-Error "The build environment does not match the pinned Aurora Voice Runtime versions."
    }
    $env:AURORA_FULL_VOICE_BUILD = "1"
    $env:AURORA_VOICE_CODEC_OVERLAY = (Resolve-Path -LiteralPath $VoiceCodecOverlay).Path
} else {
    $env:AURORA_FULL_VOICE_BUILD = $null
    $env:AURORA_VOICE_CODEC_OVERLAY = $null
}

& $Python -m PyInstaller --version | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller is not installed in this Python environment. Run: & '$Python' -m pip install pyinstaller"
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "assets"))) {
    Write-Error "Missing release resource directory: assets"
}

if ($FullVoice) {
    Write-Host "Building the pinned Full Voice Runtime after the explicit codec license gate. FFmpeg.exe is not bundled."
} else {
    Write-Host "FFmpeg/PyAV codec libraries and optional Voice runtimes are not bundled in this Core-only test package."
}

& $Python -m PyInstaller --noconfirm --clean "Project Aurora.spec"
$buildExitCode = $LASTEXITCODE
$env:AURORA_FULL_VOICE_BUILD = $null
$env:AURORA_VOICE_CODEC_OVERLAY = $null
if ($buildExitCode -ne 0) {
    Write-Error "PyInstaller build failed."
}

$buildProfile = if ($FullVoice) { 'Full' } else { 'Core' }
$distRoot = Join-Path $projectRoot "dist\Aurora-$buildProfile"
if (-not (Test-Path -LiteralPath (Join-Path $distRoot "Aurora.exe"))) {
    Write-Error "Build output missing: dist\Aurora\Aurora.exe"
}

foreach ($required in @(
    "Aurora.exe",
    "_internal",
    "_internal\assets",
    "_internal\config\default_settings.json",
    "_internal\config\voice_runtime_build.json",
    "_internal\locales",
    "_internal\customtkinter\assets"
)) {
    $path = Join-Path $distRoot $required
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Error "Release output check failed: dist\Aurora\$required"
    }
}

Write-Host "Build complete: $distRoot\Aurora.exe"

if ($FullVoice) {
    $integrityPath = Join-Path $distRoot "voice-runtime-integrity.json"
    & $Python $voiceValidator --policy $voicePolicy --build-root $distRoot --output $integrityPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $integrityPath)) {
        Write-Error "Voice Runtime integrity manifest generation failed."
    }
    Write-Host "Full Voice Build integrity manifest: $integrityPath"
}
