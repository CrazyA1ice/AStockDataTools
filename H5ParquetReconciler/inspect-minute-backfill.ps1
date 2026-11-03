# Read-only status display for minute conversion. No worker launch or market writes.
param([string]$JobId = '', [int]$Tail = 25)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$jobs=Join-Path $module 'work\minute_gui\jobs'
if(-not (Test-Path -LiteralPath $jobs -PathType Container)){throw "Minute job directory not found: $jobs"}
if([string]::IsNullOrWhiteSpace($JobId)){
    $choice=Get-ChildItem -LiteralPath $jobs -Directory |
        Where-Object { $_.Name -match '^[a-f0-9]{12}$' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'config.json') -PathType Leaf) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if($null -eq $choice){throw 'No real minute GUI jobs were found'}
    $JobId=$choice.Name
}
if($JobId -notmatch '^[a-f0-9]{12}$'){throw 'Require 12 lowercase hex job ID'}
if($Tail -lt 1 -or $Tail -gt 100){throw 'Tail must be 1..100 lines'}
$job=Join-Path $jobs $JobId
if(-not (Test-Path -LiteralPath $job -PathType Container)){throw "Unknown job: $JobId"}
Write-Host "===== Minute job $JobId ====="
$stateFile=Join-Path $job 'state.json'
if(Test-Path -LiteralPath $stateFile -PathType Leaf){
    $s=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $keys=@('status','done','total','current','last_error','pid')
    foreach($key in $keys){
        if($s.PSObject.Properties.Name -contains $key){
            Write-Host ("{0}: {1}" -f $key,$s.$key)
        }
    }
    if($null -ne $s.pid -and "$($s.pid)" -match '^\d+$'){
        $proc=Get-Process -Id ([int]$s.pid) -ErrorAction SilentlyContinue
        if($null -ne $proc){
            Write-Host ("OS process: running, PID={0}, CPU={1}" -f $proc.Id,$proc.CPU)
        }else{
            Write-Host "OS process: PID $($s.pid) not found (task may have completed, failed or exited)"
        }
    }
}else{
    Write-Host 'State not written yet; inspect the worker stdout for startup errors.'
}
$log=Join-Path $job 'activity.log'
if(Test-Path -LiteralPath $log -PathType Leaf){
    Write-Host "===== Last $Tail actual activity lines ====="
    Get-Content -LiteralPath $log -Encoding UTF8 -Tail $Tail
}else{Write-Host 'Activity log not yet available.'}
$stdout=Join-Path $job 'worker-stdout.log'
if(Test-Path -LiteralPath $stdout -PathType Leaf){
    Write-Host "===== Last $Tail redirected worker stdout/stderr lines ====="
    Get-Content -LiteralPath $stdout -Encoding UTF8 -Tail $Tail
}
Write-Host 'This command did not start/resume/pause/modify any conversion.'
