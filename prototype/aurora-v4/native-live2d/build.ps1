param(
    [Parameter(Mandatory=$true)][string]$SdkRoot,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\runtime-local\live2d')
)
$ErrorActionPreference='Stop'
$sdk=(Resolve-Path -LiteralPath $SdkRoot).Path
$output=[IO.Path]::GetFullPath($OutputDirectory)
# Build only Aurora-owned sources and external read-only SDK inputs. No SDK copy.
cmake -S $PSScriptRoot -B (Join-Path $output 'build') -G 'Visual Studio 17 2022' -A x64 "-DCUBISM_SDK_ROOT=$sdk"
if($LASTEXITCODE){throw 'Native configure failed'}
cmake --build (Join-Path $output 'build') --config Release --parallel 4
if($LASTEXITCODE){throw 'Native build failed'}
cargo build --release --manifest-path (Join-Path $PSScriptRoot 'host\Cargo.toml')
if($LASTEXITCODE){throw 'Rust host build failed'}
New-Item -ItemType Directory -Force -Path (Join-Path $output 'bin') | Out-Null
Copy-Item -LiteralPath (Join-Path $output 'build\Release\aurora_live2d.dll') -Destination (Join-Path $output 'bin')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'host\target\release\aurora-live2d-host.exe') -Destination (Join-Path $output 'bin')
Write-Output "Built native host in $output\bin; configure the SDK shader and model locations separately."
