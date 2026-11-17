param(
    [string]$Root = "D:\stock",
    [string]$FinanceDir = "D:\software\JHQMT\datadir\Finance",
    [ValidateRange(1,20)][int]$BatchSize = 5,
    [ValidateRange(1,1095)][int]$LookbackDays = 120,
    [ValidateRange(0,1440)][int]$MaxMinutes = 0,
    [ValidateRange(1,10000)][int]$MaxSymbols = 10000,
    [ValidateRange(30,3600)][int]$WorkerTimeoutSeconds = 180
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){ throw "Missing project Python" }
$work = Join-Path $PSScriptRoot "work\qmt_extra"
$logdir = Join-Path $work "daily-logs"
New-Item -ItemType Directory -Path $logdir -Force | Out-Null
$log = Join-Path $logdir ("financial-daily-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
Start-Transcript -Path $log -ErrorAction Stop | Out-Null
try {
    Set-Location -LiteralPath $repo
    $env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
    Write-Host "QMT_FINANCIAL_DAILY_START=$((Get-Date).ToString('o'))"
    Write-Host "QMT_FINANCIAL_DAILY_LOG=$log"
    $budget=if($MaxMinutes -eq 0){'UNLIMITED'}else{[string]$MaxMinutes}
    Write-Host ('QMT_FINANCIAL_DAILY_TIME_BUDGET='+$budget)
    if(-not(Test-Path -LiteralPath $FinanceDir -PathType Container)){ throw "Required QMT Finance cache directory missing" }
    $cli = @("-u","-B",(Join-Path $PSScriptRoot "qmt_extra_financial_cache_import.py"),"--root",$Root,"--mode","daily","--finance-dir",$FinanceDir,"--batch-size",[string]$BatchSize,"--max-symbols",[string]$MaxSymbols,"--max-minutes",[string]$MaxMinutes,"--worker-timeout-seconds",[string]$WorkerTimeoutSeconds,"--lookback-days",[string]$LookbackDays,"--apply")
    & $python @cli
    if($LASTEXITCODE -ne 0){ throw "QMT financial daily incremental job failed" }
    Write-Host "QMT_FINANCIAL_DAILY_FINISHED=$((Get-Date).ToString('o'))"
}
finally {
    Stop-Transcript | Out-Null
}
