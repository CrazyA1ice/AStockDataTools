# Separate observer; no QMT invocation; does not change the 20:05 task.
param([switch]$ApproveSelfSend, [switch]$PreviewOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $MyInvocation.MyCommand.Path
$repo=Split-Path -Parent $module
$py=Join-Path $repo '.venv\Scripts\python.exe'
$observer=Join-Path $module 'market_wecom_report.py'
if(!(Test-Path -LiteralPath $py -PathType Leaf)){throw 'MARKET_WECOM_PYTHON_NOT_FOUND'}
if(!(Test-Path -LiteralPath $observer -PathType Leaf)){throw 'MARKET_WECOM_OBSERVER_NOT_FOUND'}
$folder=Join-Path $module 'work\wecom-report-monitor'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$log=Join-Path $folder ((Get-Date).ToString('yyyyMMdd-HHmmss')+'.log')
Start-Transcript -LiteralPath $log -ErrorAction Stop | Out-Null
try {
    if($PreviewOnly){
        & $py -u -B $observer --mode preview
    }else{
        if(-not $ApproveSelfSend){throw 'MARKET_WECOM_EXPLICIT_SELF_SEND_APPROVAL_REQUIRED'}
        & $py -u -B $observer --mode watch --approve-self-send
    }
    if($LASTEXITCODE -ne 0){throw ('MARKET_WECOM_OBSERVER_EXIT_'+$LASTEXITCODE)}
}finally{
    Stop-Transcript | Out-Null
}
