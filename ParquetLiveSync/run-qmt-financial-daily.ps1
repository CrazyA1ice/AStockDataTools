param(
    [string]$Root = "D:\stock",
    [ValidateRange(1,20)][int]$BatchSize = 5,
    [ValidateRange(1,1095)][int]$LookbackDays = 120,
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
    & $python -u -B (Join-Path $PSScriptRoot "qmt_extra_financial_cache_import.py") --root $Root --mode daily --batch-size $BatchSize --max-symbols 6000 --max-minutes 1440 --worker-timeout-seconds $WorkerTimeoutSeconds --lookback-days $LookbackDays --apply
    if($LASTEXITCODE -ne 0){ throw "QMT financial daily incremental job failed" }
    Write-Host "QMT_FINANCIAL_DAILY_FINISHED=$((Get-Date).ToString('o'))"
}
finally {
    Stop-Transcript | Out-Null
}
