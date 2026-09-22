# Install the pinned official runtime only; never download or alter a model.
[CmdletBinding()]
param([string]$RuntimeRoot = $env:LOCALAPPDATA)
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
$destination = Join-Path $RuntimeRoot $manifest.install_directory
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$archive = Join-Path $destination ([Uri]$manifest.url).Segments[-1]
$executable = Join-Path $destination 'llama-server.exe'
if (@(Get-Process -Name llama-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable }).Count) {
    throw 'Close the Aurora-owned runtime before installing its files.'
}
if (!(Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri $manifest.url -OutFile $archive
}
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actual -ne $manifest.sha256) { throw 'Official runtime archive checksum mismatch; nothing extracted.' }
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
Invoke-WebRequest -Uri $manifest.license_url -OutFile (Join-Path $destination 'LICENSE-llama.cpp')
& (Join-Path $destination 'llama-server.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Runtime version probe failed.' }
Write-Output 'Pinned Aurora Vulkan runtime installed. Model files were not accessed.'
