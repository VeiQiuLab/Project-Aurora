param(
    [string]$ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$installerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $installerRoot
$scriptPath = Join-Path $installerRoot "Aurora.iss"
$distRoot = Join-Path $projectRoot "dist\Aurora"

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

if (-not $Python) {
    Write-Error "Python 3.12 is required to read Aurora release metadata. Pass -Python explicitly."
}

Push-Location $projectRoot
try {
    $versionJson = & $Python -c "import json; from modules.version import VERSION, WINDOWS_VERSION; print(json.dumps({'version': VERSION, 'windows_version': WINDOWS_VERSION}))"
}
finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0 -or -not $versionJson) {
    Write-Error "Unable to read release metadata from modules/version.py"
}
$versionInfo = $versionJson | ConvertFrom-Json
$releaseVersion = $versionInfo.version
$windowsVersion = $versionInfo.windows_version
$setupPath = Join-Path $installerRoot "Aurora-v$releaseVersion-Setup.exe"

function Resolve-IsccPath {
    param([string]$PreferredPath)

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        $PreferredPath,
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    return $PreferredPath
}

$ISCC = Resolve-IsccPath -PreferredPath $ISCC

if (-not (Test-Path -LiteralPath $ISCC)) {
    Write-Error "Inno Setup compiler not found. Install Inno Setup 6 or rerun with: .\installer\build_installer.ps1 -ISCC C:\Path\To\ISCC.exe"
}

foreach ($required in @("Aurora.exe", "_internal", "assets", "tools\ffmpeg.exe")) {
    $path = Join-Path $distRoot $required
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Error "Release directory is incomplete: dist\Aurora\$required"
    }
}

Push-Location $installerRoot
try {
    & $ISCC "/DMyAppVersion=$releaseVersion" "/DMyAppWindowsVersion=$windowsVersion" $scriptPath
}
finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup build failed."
}

if (-not (Test-Path -LiteralPath $setupPath)) {
    Write-Error "Installer output missing: installer\Aurora-v$releaseVersion-Setup.exe"
}

Write-Host "Installer complete: installer\Aurora-v$releaseVersion-Setup.exe"
