param([Parameter(Mandatory=$true)][int]$TargetProcessId)
# Task-owned process tree only. CPU is percent of one core (not whole machine).
$taskAll = @(Get-CimInstance Win32_Process)
$taskIds = @($TargetProcessId)
do {
    $taskAdded = @($taskAll | Where-Object { $_.ParentProcessId -in $taskIds -and $_.ProcessId -notin $taskIds } | ForEach-Object { [int]$_.ProcessId })
    $taskIds += $taskAdded
} while ($taskAdded.Count -gt 0)
$taskStart = @{}
$taskGpuBefore = @{}
$taskGpuAvailable = $true
try {
    Get-CimInstance Win32_PerfRawData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop | Where-Object {
        $_.Name -match '^pid_(\d+)_' -and [int]$Matches[1] -in $taskIds
    } | ForEach-Object { $taskGpuBefore[$_.Name] = $_ }
} catch { $taskGpuAvailable = $false }
Get-Process -Id $taskIds -ErrorAction SilentlyContinue | ForEach-Object { $taskStart[$_.Id] = $_.TotalProcessorTime.TotalSeconds }
$taskClock = [Diagnostics.Stopwatch]::StartNew()
Start-Sleep -Milliseconds 1200
$taskProcesses = @(Get-Process -Id $taskIds -ErrorAction SilentlyContinue)
$taskSeconds = $taskClock.Elapsed.TotalSeconds
$taskGpu = @()
$taskEngines = @()
try {
    $taskGpu = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory -ErrorAction Stop | Where-Object { $_.Name -match '^pid_(\d+)_' -and [int]$Matches[1] -in $taskIds })
    # PERF_100NSEC_TIMER (542180608): 100 * delta(counter) / delta(Sys100NS).
    # Two explicit raw samples avoid first-sample/whole-percent formatted zeros.
    # https://learn.microsoft.com/en-us/windows/win32/wmisdk/timer-algorithm-counter-types
    $taskEngines = @(Get-CimInstance Win32_PerfRawData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop | Where-Object {
        $taskGpuBefore.ContainsKey($_.Name)
    } | ForEach-Object {
        $taskPrevious = $taskGpuBefore[$_.Name]
        $taskElapsed = [decimal]$_.Timestamp_Sys100NS - [decimal]$taskPrevious.Timestamp_Sys100NS
        $taskActive = [decimal]$_.UtilizationPercentage - [decimal]$taskPrevious.UtilizationPercentage
        if ($taskElapsed -gt 0 -and $taskActive -ge 0) {
            [pscustomobject]@{ Name=$_.Name; UtilizationPercentage=[double](100 * $taskActive / $taskElapsed) }
        }
    })
} catch { $taskGpuAvailable = $false }
$taskRows = @($taskProcesses | ForEach-Object {
    $taskPid = $_.Id
    $taskMemory = @($taskGpu | Where-Object { $_.Name -match "^pid_${taskPid}_" })
    $taskUsage = @($taskEngines | Where-Object { $_.Name -match "^pid_${taskPid}_" })
    [pscustomobject]@{
        pid = $taskPid
        name = $_.ProcessName
        cpuOneCorePercent = if ($taskStart.ContainsKey($taskPid)) { 100 * ($_.TotalProcessorTime.TotalSeconds - $taskStart[$taskPid]) / $taskSeconds } else { $null }
        workingSetBytes = $_.WorkingSet64
        handles = $_.HandleCount
        threads = $_.Threads.Count
        dedicatedGpuBytes = if ($taskMemory.Count) { ($taskMemory | Measure-Object DedicatedUsage -Sum).Sum } else { $null }
        gpuEnginePercentSum = if ($taskUsage.Count) { ($taskUsage | Measure-Object UtilizationPercentage -Sum).Sum } else { $null }
    }
})
[pscustomobject]@{ intervalSeconds=$taskSeconds; gpuCountersAvailable=$taskGpuAvailable; processes=$taskRows } | ConvertTo-Json -Depth 5 -Compress
