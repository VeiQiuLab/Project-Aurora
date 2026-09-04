param(
    [string]$Python = "",
    [string]$OutputPath = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildScript = Join-Path $projectRoot "build_exe.ps1"
$distRoot = Join-Path $projectRoot "dist\Aurora"
$portableRoot = Join-Path $projectRoot "build\portable-test"
$stageRoot = Join-Path $portableRoot "Aurora-Windows-Test"
$validator = Join-Path $projectRoot "scripts\validate_portable_package.py"

function Resolve-BuildPython {
    param([string]$PreferredPath)

    if ($PreferredPath) {
        if (-not (Test-Path -LiteralPath $PreferredPath -PathType Leaf)) {
            Write-Error "Explicit Python executable not found: $PreferredPath"
        }
        return (Resolve-Path -LiteralPath $PreferredPath).Path
    }

    $candidates = @()
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source) {
        $candidates += $pythonCommand.Source
    }
    $candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    Write-Error "Full CPython 3.12 is required. Pass -Python C:\Path\To\python.exe."
}

$Python = Resolve-BuildPython -PreferredPath $Python
if (-not $SkipBuild) {
    & $buildScript -Python $Python
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Aurora executable build failed."
    }
}

foreach ($required in @(
    "Aurora.exe",
    "_internal",
    "_internal\config\default_settings.json",
    "_internal\locales",
    "_internal\customtkinter\assets"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $distRoot $required))) {
        Write-Error "Portable source is incomplete: dist\Aurora\$required"
    }
}

if (Test-Path -LiteralPath $portableRoot) {
    $resolvedProject = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
    $resolvedPortable = [System.IO.Path]::GetFullPath($portableRoot)
    if (-not $resolvedPortable.StartsWith($resolvedProject + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Write-Error "Refusing to clean a staging path outside the project build directory."
    }
    Remove-Item -LiteralPath $portableRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
Get-ChildItem -LiteralPath $distRoot -Force | Copy-Item -Destination $stageRoot -Recurse -Force

$forbiddenValues = @(
    $env:USERPROFILE,
    ".codex",
    "codex-runtimes"
) | Where-Object { $_ }
if ($projectRoot.Length -ge 8) {
    $forbiddenValues += $projectRoot
}
$validatorArgs = @($validator, $stageRoot)
foreach ($value in $forbiddenValues) {
    $validatorArgs += @("--forbidden-text", $value)
}
& $Python @validatorArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Portable package privacy validation failed."
}

if (-not $OutputPath) {
    $OutputPath = Join-Path $projectRoot "dist\Aurora-Windows-Test.zip"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $projectRoot $OutputPath
}
$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if (Test-Path -LiteralPath $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stageRoot,
    $OutputPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
)

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
    Write-Error "Portable ZIP was not created: $OutputPath"
}
$hash = Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256
Write-Host "Portable ZIP: $($hash.Path)"
Write-Host "SHA-256: $($hash.Hash)"
