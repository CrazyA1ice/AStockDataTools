# PowerShell 5.1 AST safety regression: never creates tasks or touches market files.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSScriptRoot
$installer=Join-Path $module 'install-schedule.ps1'
$runner=Join-Path $module 'scheduled-afternoon-update.ps1'
$catchup=Join-Path $module 'run-market-catchup.ps1'
foreach($path in @($installer,$runner,$catchup)){
    if(-not [IO.File]::Exists($path)){throw ('Required source missing: '+$path)}
    $tokens=$null
    $issues=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $path,[ref]$tokens,[ref]$issues)
    if(@($issues).Count -gt 0){
        throw ('PowerShell AST invalid: '+$path+' '+[string]$issues[0])
    }
}
$i=[IO.File]::ReadAllText($installer)
$r=[IO.File]::ReadAllText($runner)
$c=[IO.File]::ReadAllText($catchup)
if($i -notmatch 'WindowStyle Normal' -or $i -match 'WindowStyle Hidden'){
    throw 'Task action console is not visibly configured'
}
if($i -match 'NoExit'){throw 'Never leave scheduled task artificially running'}
if($i -notmatch 'MultipleInstances IgnoreNew' -or
   $i -notmatch "LogonType Interactive"){
    throw 'Scheduled task collision or QMT login invariant changed'
}
if($r -notmatch 'AStockDataTools2005AllStages' -or
   $r -notmatch 'WaitOne\(0\)' -or
   $r -notmatch 'MARKET_2005_ALREADY_RUNNING'){
    throw 'Cross-process scheduled/manual mutual exclusion missing'
}
if($r -notmatch 'PRE_CUTOFF_HISTORY_ONLY' -or
   $r -notmatch 'if\(-not \$HistoryOnly\)' -or
   $r -notmatch 'run-market-catchup.ps1'){
    throw 'No safe delayed-run or market catch-up path'
}
if($r -notmatch 'PARTIAL_DATA_VALIDATION' -or
   $r -notmatch 'last-afternoon-unified.json'){
    throw 'Partial quality outcomes or durable status missing'
}
if($c -notmatch 'MaxDays 30' -or
   $c -notmatch 'AddDays\(30\)' -or
   $c -notmatch 'TimeOfDay' -or
   $c -notmatch '20 -Minutes 5'){
    throw 'Market catch-up must preserve bounded windows and 20:05 cutoff'
}
Write-Host 'PASS_VISIBLE_TASK_GUI_CATCHUP_AST_NO_LIVE_FILES_OR_TASK_CHANGES'
