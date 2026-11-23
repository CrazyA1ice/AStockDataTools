# Market update notification: durable WeCom provider, NEVER Windows Toast/Popup.
# Without a private opt-in configuration, keep a local outbox receipt rather
# than pretending the user received an external message.
param(
    [ValidateSet('SUCCESS','PARTIAL','FAILED')][string]$Status='FAILED',
    [string]$Summary='',
    [string]$LogPath='',
    [string]$StatusPath='',
    [string]$ExpectedStart='',
    [switch]$DryRun
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$python=Join-Path $repo '.venv\Scripts\python.exe'
$sender=Join-Path $module 'market_update_push.py'
$private=Join-Path $module 'work\qmt_extra\market-notification.private.json'
$outbox=Join-Path $module 'work\qmt_extra\market-notification-outbox'
Write-Host ('MARKET_NOTIFICATION_STATUS='+$Status)
Write-Host 'MARKET_NOTIFICATION_CHANNEL=WECOM_EXTERNAL_PUSH'
Write-Host 'MARKET_NOTIFICATION_WINDOWS_TOAST_DISABLED=TRUE'
if($DryRun){
    if($Summary){Write-Host ('MARKET_NOTIFICATION_TEXT='+$Summary)}
    Write-Host 'MARKET_NOTIFICATION_DRY_RUN_NO_DESKTOP=TRUE'
    return
}
if(-not(Test-Path -LiteralPath $python -PathType Leaf) -or
   -not(Test-Path -LiteralPath $sender -PathType Leaf)){
    Write-Host 'MARKET_NOTIFICATION_SENDER_MISSING=TRUE'
    exit 2
}
if(-not $StatusPath -or -not(Test-Path -LiteralPath $StatusPath -PathType Leaf)){
    Write-Host 'MARKET_NOTIFICATION_SAME_RUN_RECEIPT_MISSING=TRUE'
    exit 2
}
$argv=@('-u','-B',$sender,'--receipt',$StatusPath,
        '--config',$private,'--outbox',$outbox)
if($ExpectedStart){$argv+=@('--expected-start-local',$ExpectedStart)}
# The Python CLI intentionally never emits credentials, full URLs, or raw
# provider exceptions. Status 0 means API ACK, NOT handset delivery proof.
& $python @argv
$code=$LASTEXITCODE
if($code -ne 0){
    Write-Host ('MARKET_NOTIFICATION_PUSH_NOT_CONFIRMED=TRUE exit='+$code)
    exit 2
}
Write-Host 'MARKET_NOTIFICATION_PUSH_PROVIDER_ACK=TRUE'
