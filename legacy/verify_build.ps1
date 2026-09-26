param([Parameter(Mandatory=$true)][string]$DistRoot)
$ErrorActionPreference = 'Stop'
$marker = Join-Path $DistRoot 'legacy-build.json'
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw 'Unverified legacy binary: rebuild with build_exe.ps1 -Legacy before packaging.'
}
$stamp = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
$hash = (Get-FileHash -LiteralPath (Join-Path $DistRoot 'Aurora.exe') -Algorithm SHA256).Hash
if ($stamp.entrypoint -ne 'legacy.tk_desktop' -or $stamp.data_directory -ne 'Aurora-Legacy' -or $stamp.exe_sha256 -ne $hash) {
    throw 'Legacy artifact identity mismatch; old production-writing EXEs must not be repackaged.'
}
