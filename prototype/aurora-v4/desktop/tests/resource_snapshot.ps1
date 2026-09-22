param([Parameter(Mandatory=$true)][int]$TargetProcessId)
$taskProcesses = @(Get-CimInstance Win32_Process)
$taskIds = @($TargetProcessId)
do {
    $taskAdded = @($taskProcesses | Where-Object { $_.ParentProcessId -in $taskIds -and $_.ProcessId -notin $taskIds } | ForEach-Object { [int]$_.ProcessId })
    $taskIds += $taskAdded
} while ($taskAdded.Count -gt 0)
$taskWebviews = @($taskProcesses | Where-Object { $_.ProcessId -in $taskIds -and $_.Name -eq 'msedgewebview2.exe' })
$taskGpu = @()
$taskGpuAvailable = $true
try {
    $taskGpu = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory -ErrorAction Stop | Where-Object {
        $_.Name -match '^pid_(\d+)_' -and [int]$Matches[1] -in @($taskWebviews.ProcessId)
    })
} catch { $taskGpuAvailable = $false }
[pscustomobject]@{
    processId = $TargetProcessId
    auroraCount = @($taskProcesses | Where-Object Name -eq 'aurora-v4-desktop.exe').Count
    pythonCount = @($taskProcesses | Where-Object { $_.ProcessId -in $taskIds -and $_.Name -eq 'python.exe' }).Count
    pythonPids = @($taskProcesses | Where-Object { $_.ProcessId -in $taskIds -and $_.Name -eq 'python.exe' } | ForEach-Object { $_.ProcessId })
    webviewCount = $taskWebviews.Count
    webviewWorkingSetBytes = ($taskWebviews | Measure-Object WorkingSetSize -Sum).Sum
    gpuCountersAvailable = $taskGpuAvailable -and $taskGpu.Count -gt 0
    dedicatedGpuBytes = if ($taskGpu.Count -gt 0) { ($taskGpu | Measure-Object DedicatedUsage -Sum).Sum } else { $null }
    sharedGpuBytes = if ($taskGpu.Count -gt 0) { ($taskGpu | Measure-Object SharedUsage -Sum).Sum } else { $null }
} | ConvertTo-Json -Compress
