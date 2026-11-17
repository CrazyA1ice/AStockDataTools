# Pure no-UI test: every outcome creates a human-readable message.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$notifier=Join-Path (Split-Path -Parent $PSScriptRoot) 'notify-market-update.ps1'
if(-not([IO.File]::Exists($notifier))){throw 'Notification entry missing'}
foreach($state in @('SUCCESS','PARTIAL','FAILED')){
    $output=@(& $notifier -Status $state -Summary 'TEST: K线/财务/板块/除权' -LogPath 'C:\test-only.log' -DryRun)
    $result=$output -join "`n"
    if($result -notmatch ('MARKET_NOTIFICATION_STATUS='+$state) -or
       $result -notmatch 'MARKET_NOTIFICATION_DRY_RUN_NO_DESKTOP=TRUE' -or
       $result -notmatch 'TEST: K线/财务/板块/除权'){
        throw ('Missing notification payload: '+$state)
    }
}
Write-Host 'PASS_MARKET_NOTIFICATION_THREE_OUTCOMES_NO_DESKTOP'
