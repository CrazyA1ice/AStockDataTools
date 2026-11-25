# Pinned Windows PowerShell 5.1: 142 offline tests, one 4-symbol QMT Capital cache read.
# Does not deploy, download, clear pending, select active pins, or commit Parquet.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepoRoot,
      [Parameter(Mandatory=$true)][string]$PilotCommit)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$base=Join-Path $RepoRoot 'ParquetLiveSync'
$py=Join-Path $RepoRoot '.venv\Scripts\python.exe'
$ledger=Join-Path $base 'work\qmt_extra\financial-cache-progress.json'
$expectedHead='2b5c1bd28f8df4d4512dd933e50b1be50741f6a6'
$expectedLedger='4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1'
$expectedProduction=@{
'market_daily_verification.py'='f20cc512eada2e90d0a639e17548b4f0809fa720'
'scheduled-afternoon-update.ps1'='93b0b870ce6d49b5485a55f577c5e49e0d027ea7'
'notify-market-update.ps1'='e91d4b31ee558d874948769231474e9a16f9bbe3'
'qmt_extra_financial_cache_import.py'='a68a497f27084ef00397d1f6e921f34142240fe7'
'qmt_extra_financial_cache_worker.py'='d6d9c942729f402a10045ac8211c7e2759f46a73'
'qmt_extra_data.py'='c68eb91c8f5b133a9c5f900e35b2d7f46daedb88'
}
$files=@(
@{Path='ParquetLiveSync/finance_pending_audit_once.py';Blob='95debbd4bbe3566252c7e6f0066ba72d75754bca'}
@{Path='ParquetLiveSync/tests/test_finance_pending_audit_once.py';Blob='78f704081e0d157d1358da409e7afe6e99a7bcd3'}
@{Path='ParquetLiveSync/finance_priority_three_audit_once.py';Blob='f6c4c3c7495e8c401ba49c77d206a63f8b508544'}
@{Path='ParquetLiveSync/tests/test_finance_priority_three_audit_once.py';Blob='911967e172b6a776e4773e2a721a3669f9a8ff65'}
@{Path='ParquetLiveSync/tests/test_finance_priority_three_disclosure_proof.py';Blob='ca2113db8c262eca5cad6375aa380303077437d3'}
@{Path='ParquetLiveSync/qmt_finance_versioned_recovery_preview.py';Blob='e1b0411354e304b4380006a85b05e204d69eb51e'}
@{Path='ParquetLiveSync/tests/test_qmt_finance_versioned_recovery_preview.py';Blob='748f03a3c259595992dd7d330f4cecc125da0e51'}
@{Path='ParquetLiveSync/qmt_finance_five_pilot_once.py';Blob='ac376c8d3afe3463a6c642a8dcdd93a48277445d'}
@{Path='ParquetLiveSync/tests/test_qmt_finance_five_pilot_once.py';Blob='93a041b6c557394eb75a8522f44ef3acbe09e96d'}
@{Path='ParquetLiveSync/qmt_finance_capital_four_diagnostic_once.py';Blob='ae4145e9a31759c00c72fcfe8ad251cb3bd8a3cf'}
@{Path='ParquetLiveSync/tests/test_qmt_finance_capital_four_diagnostic_once.py';Blob='2c3331f7db032c08f910dba2a9d9f04674c8fda6'}
@{Path='ParquetLiveSync/docs/finance-priority-three-adjudication-manifest-20261125.json';Blob='3ba609a9b9200ee18093104fb29dd205acaecd68'}
)
$tests=@(
'test_finance_pending_audit_once.py',
'test_finance_priority_three_audit_once.py',
'test_finance_priority_three_disclosure_proof.py',
'test_qmt_finance_versioned_recovery_preview.py',
'test_qmt_finance_five_pilot_once.py',
'test_qmt_finance_capital_four_diagnostic_once.py'
)
function CheckWindow {
$ct=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')).TimeOfDay
if($ct -ge (New-TimeSpan -Hours 18 -Minutes 30) -and $ct -lt (New-TimeSpan -Hours 23 -Minutes 35)){throw 'PROTECTED_NIGHTLY_WINDOW_STOP'}
}
function HashMatches([string]$path,[string]$sha){
if(!(Test-Path -LiteralPath $path -PathType Leaf)){throw "FILE_MISSING=$path"}
$got=git -C $RepoRoot hash-object -- $path
if($LASTEXITCODE -ne 0 -or $got.Trim() -ne $sha){throw "FILE_BLOB_MISMATCH=$path"}
}
CheckWindow
if($PilotCommit -notmatch '^[0-9a-f]{40}$'){throw 'INVALID_PILOT_COMMIT'}
if(!(Test-Path -LiteralPath $py -PathType Leaf)){throw 'PYTHON_MISSING'}
if(!(Test-Path -LiteralPath $ledger -PathType Leaf)){throw 'LEDGER_MISSING'}
$head=git -C $RepoRoot rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $head.Trim() -ne $expectedHead){throw 'CANONICAL_HEAD_CHANGED_STOP'}
$revision=git -C $RepoRoot rev-parse $PilotCommit
if($LASTEXITCODE -ne 0 -or $revision.Trim() -ne $PilotCommit){throw 'PINNED_PILOT_COMMIT_MISSING_STOP'}
foreach($name in $expectedProduction.Keys){HashMatches (Join-Path $base $name) $expectedProduction[$name]}
$before=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash.ToLowerInvariant()
if($before -ne $expectedLedger){throw 'LEDGER_CHANGED_FROM_VERIFIED_20261124_AUDIT_STOP'}
$mutex=[System.Threading.Mutex]::new($false,'Local\AStockDataTools2005AllStages')
$held=$false
$stage=$null
try {
try{$held=$mutex.WaitOne(0)}catch [System.Threading.AbandonedMutexException]{$held=$true}
if(!$held){throw 'RUNNER_MUTEX_BUSY_STOP'}
$task=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\' -ErrorAction Stop
if($task.State -ne 'Ready'){throw 'TASK_NOT_IDLE_STOP'}
$actions=@($task.Actions)
if($actions.Count -ne 1 -or ([string]$actions[0].Arguments) -notmatch 'scheduled-afternoon-update\.ps1'){throw 'TASK_ACTION_CHANGED_STOP'}
CheckWindow
$stage=Join-Path $env:TEMP ('finance-five-pilot-'+[guid]::NewGuid().ToString('N'))
$dir=Join-Path $stage 'ParquetLiveSync'
New-Item -ItemType Directory -Path (Join-Path $dir 'tests') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dir 'docs') -Force | Out-Null
$gitexe=(Get-Command git -ErrorAction Stop).Source
foreach($item in $files){
$spec=$PilotCommit+':'+$item.Path
$blob=git -C $RepoRoot rev-parse $spec
if($LASTEXITCODE -ne 0 -or $blob.Trim() -ne $item.Blob){throw "REVIEWED_BLOB_CHANGED_STOP=$spec"}
$relative=$item.Path.Substring('ParquetLiveSync/'.Length).Replace('/','\')
$dest=Join-Path $dir $relative
$psi=New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName=$gitexe
$psi.Arguments='cat-file blob '+$blob.Trim()
$psi.WorkingDirectory=$RepoRoot
$psi.UseShellExecute=$false
$psi.RedirectStandardOutput=$true
$psi.RedirectStandardError=$true
$p=[System.Diagnostics.Process]::Start($psi)
try{
$stream=[System.IO.File]::Open($dest,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
try{$p.StandardOutput.BaseStream.CopyTo($stream)}finally{$stream.Dispose()}
$stderr=$p.StandardError.ReadToEnd()
$p.WaitForExit()
if($p.ExitCode -ne 0){throw "GIT_STAGE_FAILED=$spec $stderr"}
}finally{$p.Dispose()}
HashMatches $dest $item.Blob
}
Write-Host '===FINANCE_OFFLINE_TESTS_142==='
foreach($name in $tests){
CheckWindow
& $py -B (Join-Path $dir ('tests\'+$name)) -q
if($LASTEXITCODE -ne 0){throw "FINANCE_OFFLINE_TEST_FAILED=$name"}
Write-Host "TEST_FILE_PASS=$name"
}
Write-Host 'FINANCE_OFFLINE_142_TESTS_PASS'
$task2=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\' -ErrorAction Stop
if($task2.State -ne 'Ready'){throw 'TASK_BECAME_BUSY_STOP'}
CheckWindow
$nowHash=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash.ToLowerInvariant()
if($nowHash -ne $expectedLedger){throw 'LEDGER_CHANGED_BEFORE_QMT_PILOT_STOP'}
Write-Host '===QMT_CAPITAL_FOUR_ROOT_CAUSE_CACHE_ONLY==='
& $py -B (Join-Path $dir 'qmt_finance_capital_four_diagnostic_once.py') $base
if($LASTEXITCODE -ne 0){throw 'FOUR_CAPITAL_CAUSE_DIAG_FAILED'}
Write-Host 'FINANCE_CAPITAL_FOUR_CAUSE_DIAG_PASS_NO_DEPLOY'
}finally{
$after=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash.ToLowerInvariant()
if($after -eq $before){Write-Host 'OUTER_FINANCE_LEDGER_UNCHANGED_VERIFIED'}else{Write-Host 'OUTER_LEDGER_CHANGED_REVIEW_REQUIRED'}
if($null -ne $stage -and (Test-Path -LiteralPath $stage)){Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue}
if($held){$mutex.ReleaseMutex()}
$mutex.Dispose()
if($after -ne $before){throw 'OUTER_FINANCE_LEDGER_CHANGED_DURING_PILOT_STOP'}
}
Write-Host 'FINANCE_CAPITAL_FOUR_ROOT_CAUSE_COMPLETE_NO_DEPLOY'
