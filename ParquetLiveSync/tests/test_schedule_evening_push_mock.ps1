# Offline-only static/preview contract for one pre-midnight market chain.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSScriptRoot
$runner=Join-Path $module 'scheduled-afternoon-update.ps1'
$installer=Join-Path $module 'install-schedule.ps1'
$notify=Join-Path $module 'notify-market-update.ps1'
$activation=Join-Path $module 'activate-evening-schedule.ps1'
foreach($file in @($runner,$installer,$notify,$activation,(Join-Path $module 'run-qmt-financial-daily.ps1'))){
    $tokens=$null; $errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors)
    if($null -ne $errors -and $errors.Count -gt 0){throw ('PowerShell AST error: '+$file+' '+($errors | Out-String))}
}
$text=[IO.File]::ReadAllText($runner)
$names=@("'EIGHT_PERIODS'","'SECTORS'","'ADJUSTMENTS_ROTATING'","'FINANCIAL_DAILY'")
$offset=-1
foreach($name in $names){
    $anchor="Invoke-MarketStage -Label "+$name
    $found=$text.IndexOf($anchor,$offset+1,[StringComparison]::Ordinal)
    if($found -le $offset){throw ('Market stage order violated: '+$name)}
    $offset=$found
}
if($text -notmatch '-QMTPrimaryVersioned' -or
   $text -notmatch 'financeBudget' -or
   $text -notmatch 'AddHours\(23\).AddMinutes\(20\)' -or
   $text -notmatch 'finance_deferred_by_cutoff'){
    throw 'QMT-primary finance last, bounded night run, or defer receipt missing'
}
$notifySource=[IO.File]::ReadAllText($notify)
if($notifySource -match 'ToastNotificationManager|WScript\.Shell|\.Popup\('){
    throw 'Windows desktop notification unexpectedly enabled'
}
if($notifySource -notmatch 'market_update_push.py' -or
   $notifySource -notmatch 'ExpectedStart'){
    throw 'Full-length same-run external push not wired'
}
$installSource=[IO.File]::ReadAllText($installer)
if($installSource -notmatch 'AddHours\(20\).AddMinutes\(5\)' -or
   $installSource -notmatch 'Disable-ScheduledTask' -or
   $installSource -match 'New-ScheduledTaskSettingsSet -StartWhenAvailable'){
    throw 'One 20:05 trigger or disabled midnight finance guard missing'
}
$out=@(& $runner -Invocation Manual 6>&1) -join [Environment]::NewLine
if($out -notmatch 'MARKET_1630_SECTIONS=EIGHT_PERIODS,SECTORS,ADJUSTMENTS_ROTATING,FINANCIAL_DAILY'){
    throw 'Runner preview stages missing'
}
if($out -notmatch 'WECOM_CHUNKED_PUSH' -or $out -notmatch '23:20_CHINA'){
    throw 'Runner preview missing push or nightly deadline'
}
$activationSource=[IO.File]::ReadAllText($activation)
if($activationSource -notmatch 'CONFIRM_REAL_WECOM_CANARY_ON_HANDSET_BEFORE_APPLY' -or
   $activationSource -notmatch 'REVIEW_WORKTREE_NOT_PINNED' -or
   $activationSource -notmatch 'evening-schedule-backup-' -or
   $activationSource -notmatch 'CANONICAL_LOCAL_FILE_CHANGED_' -or
   $activationSource -notmatch 'EVENING_SCHEDULE_ACTIVATION_PREVIEW_ONLY_NO_LOCAL_CHANGES'){
    throw 'Pinned, backup-first, canary-confirmed schedule activation missing'
}
Write-Host 'PASS_SINGLE_2005_KLINE_SECTORS_ADJUSTMENTS_FINANCE_WECom_NO_DESKTOP_MOCK'
