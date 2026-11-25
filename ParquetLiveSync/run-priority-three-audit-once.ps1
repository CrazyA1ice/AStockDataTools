# Guarded test+audit launcher: never downloads, changes QMT records or deploys.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepoRoot,
      [Parameter(Mandatory=$true)][string]$AuditCommit)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$base=Join-Path $RepoRoot 'ParquetLiveSync'
$py=Join-Path $RepoRoot '.venv\Scripts\python.exe'
$ledger=Join-Path $base 'work\qmt_extra\financial-cache-progress.json'
$expected=@{
'market_daily_verification.py'='f20cc512eada2e90d0a639e17548b4f0809fa720'
'scheduled-afternoon-update.ps1'='93b0b870ce6d49b5485a55f577c5e49e0d027ea7'
'notify-market-update.ps1'='e91d4b31ee558d874948769231474e9a16f9bbe3'
'qmt_extra_financial_cache_import.py'='a68a497f27084ef00397d1f6e921f34142240fe7'
'qmt_extra_financial_cache_worker.py'='d6d9c942729f402a10045ac8211c7e2759f46a73'
'qmt_extra_data.py'='c68eb91c8f5b133a9c5f900e35b2d7f46daedb88'
}
$files=@(
@{Path='ParquetLiveSync/finance_priority_three_audit_once.py';Blob='f6c4c3c7495e8c401ba49c77d206a63f8b508544'}
@{Path='ParquetLiveSync/tests/test_finance_priority_three_audit_once.py';Blob='911967e172b6a776e4773e2a721a3669f9a8ff65'}
)
function CheckHash([string]$path,[string]$want){
if(!(Test-Path -LiteralPath $path -PathType Leaf)){throw "MISSING=$path"}
$got=git -C $RepoRoot hash-object -- $path
if($LASTEXITCODE -ne 0 -or $got.Trim() -ne $want){throw "HASH_MISMATCH=$path"}
}
function CheckWindow {
$ct=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')).TimeOfDay
if($ct -ge (New-TimeSpan -Hours 18 -Minutes 45) -and $ct -lt (New-TimeSpan -Hours 23 -Minutes 35)){throw 'SCHEDULE_WINDOW_STOP'}
}
CheckWindow
if($AuditCommit -notmatch '^[0-9a-f]{40}$'){throw 'INVALID_COMMIT_PIN'}
if(!(Test-Path -LiteralPath $py -PathType Leaf)){throw 'PYTHON_MISSING'}
if(!(Test-Path -LiteralPath $ledger -PathType Leaf)){throw 'LEDGER_MISSING'}
$head=git -C $RepoRoot rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $head.Trim() -ne '2b5c1bd28f8df4d4512dd933e50b1be50741f6a6'){throw 'CANONICAL_HEAD_CHANGED_STOP'}
$rev=git -C $RepoRoot rev-parse $AuditCommit
if($LASTEXITCODE -ne 0 -or $rev.Trim() -ne $AuditCommit){throw 'REVIEW_PIN_UNAVAILABLE'}
foreach($n in $expected.Keys){CheckHash (Join-Path $base $n) $expected[$n]}
$before=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash
$mutex=[System.Threading.Mutex]::new($false,'Local\AStockDataTools2005AllStages')
$held=$false
$stage=$null
try{
try{$held=$mutex.WaitOne(0)}catch [System.Threading.AbandonedMutexException]{$held=$true}
if(!$held){throw 'RUNNER_MUTEX_BUSY_STOP'}
$task=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\' -ErrorAction Stop
if($task.State -ne 'Ready'){throw 'TASK_NOT_READY_STOP'}
$acts=@($task.Actions)
if($acts.Count -ne 1 -or ([string]$acts[0].Arguments) -notmatch 'scheduled-afternoon-update\.ps1'){throw 'TASK_ACTION_MISMATCH_STOP'}
CheckWindow
$stage=Join-Path $env:TEMP ('finance-priority3-'+[guid]::NewGuid().ToString('N'))
$dir=Join-Path $stage 'ParquetLiveSync'
New-Item -ItemType Directory -Path (Join-Path $dir 'tests') -Force | Out-Null
$gitexe=(Get-Command git -ErrorAction Stop).Source
foreach($item in $files){
$spec=$AuditCommit+':'+$item.Path
$blob=git -C $RepoRoot rev-parse $spec
if($LASTEXITCODE -ne 0 -or $blob.Trim() -ne $item.Blob){throw "SCRIPT_BLOB_MISMATCH=$spec"}
$rel=$item.Path.Substring('ParquetLiveSync/'.Length).Replace('/','\')
$dst=Join-Path $dir $rel
$psi=New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName=$gitexe
$psi.Arguments='cat-file blob '+$blob.Trim()
$psi.WorkingDirectory=$RepoRoot
$psi.UseShellExecute=$false
$psi.RedirectStandardOutput=$true
$psi.RedirectStandardError=$true
$p=[System.Diagnostics.Process]::Start($psi)
try{
$stream=[System.IO.File]::Open($dst,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
try{$p.StandardOutput.BaseStream.CopyTo($stream)}finally{$stream.Dispose()}
$stderr=$p.StandardError.ReadToEnd()
$p.WaitForExit()
if($p.ExitCode -ne 0){throw "GIT_STAGE_FAILED=$spec $stderr"}
}finally{$p.Dispose()}
CheckHash $dst $item.Blob
}
Write-Host '===OFFLINE_TESTS==='
& $py -B (Join-Path $dir 'tests\test_finance_priority_three_audit_once.py') -q
if($LASTEXITCODE -ne 0){throw 'OFFLINE_TESTS_FAILED'}
Write-Host 'PRIORITY_THREE_OFFLINE_TESTS_PASS'
$task=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\' -ErrorAction Stop
if($task.State -ne 'Ready'){throw 'TASK_BECAME_BUSY_STOP'}
CheckWindow
Write-Host '===QMT_CACHE_ONLY_PRIORITY_THREE==='
& $py -B (Join-Path $dir 'finance_priority_three_audit_once.py') $base
if($LASTEXITCODE -ne 0){throw 'PRIORITY_THREE_AUDIT_FAILED'}
Write-Host 'FINANCE_PRIORITY_THREE_AUDIT_PASS_NO_DEPLOY'
}finally{
$after=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash
if($after -eq $before){Write-Host 'OUTER_FINANCE_LEDGER_UNCHANGED_VERIFIED'}else{Write-Host 'OUTER_FINANCE_LEDGER_CHANGED_REVIEW_REQUIRED'}
if($null -ne $stage -and (Test-Path -LiteralPath $stage)){Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue}
if($held){$mutex.ReleaseMutex()}
$mutex.Dispose()
if($after -ne $before){throw 'FINANCE_LEDGER_CHANGED_DURING_AUDIT_STOP'}
}
Write-Host 'FINANCE_PRIORITY_THREE_244_COMPLETE_NO_DEPLOY'
