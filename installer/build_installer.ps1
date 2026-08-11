param(
    [string]$ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"

$installerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $installerRoot
$scriptPath = Join-Path $installerRoot "Aurora-v3.7.2.iss"
$distRoot = Join-Path $projectRoot "dist\Aurora"
$setupPath = Join-Path $installerRoot "Aurora-v3.7.2-Setup.exe"

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
    & $ISCC $scriptPath
}
finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup build failed."
}

if (-not (Test-Path -LiteralPath $setupPath)) {
    Write-Error "Installer output missing: installer\Aurora-v3.7.2-Setup.exe"
}

Write-Host "Installer complete: installer\Aurora-v3.7.2-Setup.exe"
