# Offline-only structural contract: never launches the real updater/QMT/task.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSScriptRoot
$runner=Join-Path $module 'scheduled-afternoon-update.ps1'
$probe=Join-Path $module 'qmt_connect_preflight.py'
if(-not [IO.File]::Exists($runner) -or -not [IO.File]::Exists($probe)){
    throw 'QMT readiness gate components missing'
}
$tokens=$null
$issues=$null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $runner,[ref]$tokens,[ref]$issues)
if(@($issues).Count -gt 0){
    throw ('QMT readiness runner PowerShell syntax invalid: '+[string]$issues[0])
}
$s=[IO.File]::ReadAllText($runner)
$p=[IO.File]::ReadAllText($probe)
$first=$s.IndexOf('$qmtPreflightStatus='+"'CONNECTING'")
$retry=$s.IndexOf('for($attempt=1;$attempt -le 6;$attempt++)')
$failed=$s.IndexOf("throw 'QMT_SERVICE_UNAVAILABLE:")
$firstStage=$s.IndexOf("Invoke-MarketStage -Label 'EIGHT_PERIODS' -Script "+'$catchup')
if($first -lt 0 -or $retry -lt $first -or $failed -lt $retry -or $firstStage -lt $failed){
    throw 'QMT readiness must run and fail closed BEFORE any market stage'
}
if($s -notmatch 'Start-Sleep -Seconds 10' -or
   $s -notmatch '--timeout-seconds 25' -or
   $s -notmatch 'if\(\$attempt -lt 6\)'){
    throw 'Six bounded attempts, five 10s waits, child timeouts not guaranteed'
}
if($s -notmatch 'qmt_preflight_status=\$qmtPreflightStatus' -or
   $s -notmatch 'qmt_preflight_attempts=\[int\]\$qmtPreflightAttempts' -or
   $s -notmatch 'MARKET_2005_QMT_SERVICE_UNAVAILABLE=TRUE'){
    throw 'Last-run receipt or visible unavailable message missing'
}
if($s -notmatch 'Start-Transcript' -or
   $s -notmatch 'Stop-Transcript' -or
   $s -notmatch 'ReleaseMutex' -or
   $s -notmatch 'PARTIAL_DATA_VALIDATION'){
    throw 'Failure path lost durable logs, lock release or quality semantics'
}
if($p -match 'download_history|download_financial|get_market_data|get_financial_data|write_parquet'){
    throw 'Connection probe must never perform QMT data reads/writes'
}
if($s -notmatch 'PRE_CUTOFF_HISTORY_ONLY' -or
   $s -notmatch 'last-precutoff-market-only.json'){
    throw 'Pre-20:05 catch-up safety or separate receipt lost'
}
Write-Host 'PASS_QMT_READY_GATE_SIX_BOUNDED_MOCK_NO_QMT_OR_DATA_OR_TASK_WRITES'
