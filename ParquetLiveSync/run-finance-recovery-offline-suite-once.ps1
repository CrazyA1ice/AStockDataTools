# Windows PowerShell 5.1 compatible: 102 offline finance tests, no QMT calls.
# Fetch this launcher at a pinned Git revision; no repo checkout/reset needed.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepoRoot,
      [Parameter(Mandatory=$true)][string]$AuditCommit)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$python=Join-Path $RepoRoot '.venv\Scripts\python.exe'
$ledger=Join-Path $RepoRoot 'ParquetLiveSync\work\qmt_extra\financial-cache-progress.json'
$expectedHead='2b5c1bd28f8df4d4512dd933e50b1be50741f6a6'
$files=@(
@{Path='ParquetLiveSync/finance_pending_audit_once.py';Blob='95debbd4bbe3566252c7e6f0066ba72d75754bca'}
@{Path='ParquetLiveSync/tests/test_finance_pending_audit_once.py';Blob='78f704081e0d157d1358da409e7afe6e99a7bcd3'}
@{Path='ParquetLiveSync/finance_priority_three_audit_once.py';Blob='f6c4c3c7495e8c401ba49c77d206a63f8b508544'}
@{Path='ParquetLiveSync/tests/test_finance_priority_three_audit_once.py';Blob='911967e172b6a776e4773e2a721a3669f9a8ff65'}
@{Path='ParquetLiveSync/tests/test_finance_priority_three_disclosure_proof.py';Blob='ca2113db8c262eca5cad6375aa380303077437d3'}
@{Path='ParquetLiveSync/qmt_finance_versioned_recovery_preview.py';Blob='e1b0411354e304b4380006a85b05e204d69eb51e'}
@{Path='ParquetLiveSync/tests/test_qmt_finance_versioned_recovery_preview.py';Blob='748f03a3c259595992dd7d330f4cecc125da0e51'}
)
$tests=@(
'test_finance_pending_audit_once.py'
'test_finance_priority_three_audit_once.py'
'test_finance_priority_three_disclosure_proof.py'
'test_qmt_finance_versioned_recovery_preview.py'
)
function Protect-Time {
    $c=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')).TimeOfDay
    if($c -ge (New-TimeSpan -Hours 18 -Minutes 45) -and $c -lt (New-TimeSpan -Hours 23 -Minutes 35)){throw 'NIGHTLY_SCHEDULE_PROTECTION_STOP'}
}
Protect-Time
if($AuditCommit -notmatch '^[0-9a-f]{40}$'){throw 'INVALID_COMMIT_PIN'}
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'PYTHON_MISSING'}
if(!(Test-Path -LiteralPath $ledger -PathType Leaf)){throw 'FINANCE_LEDGER_MISSING'}
$head=git -C $RepoRoot rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $head.Trim() -ne $expectedHead){throw 'CANONICAL_HEAD_CHANGED_STOP'}
$rev=git -C $RepoRoot rev-parse $AuditCommit
if($LASTEXITCODE -ne 0 -or $rev.Trim() -ne $AuditCommit){throw 'AUDIT_COMMIT_NOT_FETCHED_STOP'}
$task=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\' -ErrorAction Stop
if($task.State -ne 'Ready'){throw 'SCHEDULED_TASK_NOT_IDLE_STOP'}
$before=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash
$stage=$null
try {
    $stage=Join-Path $env:TEMP ('finance-recovery-offline-'+[guid]::NewGuid().ToString('N'))
    $dir=Join-Path $stage 'ParquetLiveSync'
    New-Item -ItemType Directory -Path (Join-Path $dir 'tests') -Force | Out-Null
    $gitexe=(Get-Command git -ErrorAction Stop).Source
    foreach($item in $files){
        $spec=$AuditCommit+':'+$item.Path
        $blob=git -C $RepoRoot rev-parse $spec
        if($LASTEXITCODE -ne 0 -or $blob.Trim() -ne $item.Blob){throw "SOURCE_BLOB_PIN_MISMATCH=$spec"}
        $relative=$item.Path.Substring('ParquetLiveSync/'.Length).Replace('/','\')
        $dest=Join-Path $dir $relative
        $psi=New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName=$gitexe
        $psi.Arguments='cat-file blob '+$blob.Trim()
        $psi.WorkingDirectory=$RepoRoot
        $psi.UseShellExecute=$false
        $psi.RedirectStandardOutput=$true
        $psi.RedirectStandardError=$true
        $proc=[System.Diagnostics.Process]::Start($psi)
        try {
            $out=[System.IO.File]::Open($dest,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
            try { $proc.StandardOutput.BaseStream.CopyTo($out) } finally { $out.Dispose() }
            $errorText=$proc.StandardError.ReadToEnd()
            $proc.WaitForExit()
            if($proc.ExitCode -ne 0){throw "GIT_BLOB_STAGE_FAILED=$spec $errorText"}
        } finally { $proc.Dispose() }
        $staged=git -C $RepoRoot hash-object -- $dest
        if($LASTEXITCODE -ne 0 -or $staged.Trim() -ne $item.Blob){throw "STAGED_FILE_HASH_MISMATCH=$spec"}
    }
    Write-Host 'OFFLINE_SUITE=27+21+8+46=102'
    foreach($name in $tests){
        Protect-Time
        Write-Host ('TEST_FILE='+$name)
        & $python -B (Join-Path $dir ('tests\'+$name)) -q
        if($LASTEXITCODE -ne 0){throw "OFFLINE_TESTS_FAILED=$name"}
        Write-Host ('TEST_FILE_PASS='+$name)
    }
    Write-Host 'FINANCE_VERSIONED_RECOVERY_OFFLINE_102_PASS_NO_DEPLOY'
} finally {
    $after=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash
    if($after -eq $before){Write-Host 'FINANCE_LEDGER_UNCHANGED_VERIFIED'}else{Write-Host 'FINANCE_LEDGER_HASH_CHANGED_STOP'}
    if($null -ne $stage -and (Test-Path -LiteralPath $stage)){Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue}
    if($after -ne $before){throw 'LEDGER_CHANGED_DURING_OFFLINE_TESTS_STOP'}
}
