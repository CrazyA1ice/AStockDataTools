param([switch]$Install)
$ErrorActionPreference = "Stop"
if(-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core"){
    throw "Windows Task Scheduler is required"
}
$taskName = "AStockDataTools-QMT-Financial-Daily"
$repo = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run-qmt-financial-daily.ps1"
if(-not(Test-Path -LiteralPath $runner -PathType Leaf)){ throw "Daily runner missing" }
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($existing){ throw "Task already exists; refusing to overwrite $taskName" }
Write-Host "QMT_FINANCIAL_DAILY_TASK_NAME=$taskName"
Write-Host "QMT_FINANCIAL_DAILY_TASK_TIME=23:15"
Write-Host "QMT_FINANCIAL_DAILY_RUNNER=$runner"
Write-Host "QMT_FINANCIAL_DAILY_REQUIRE_QMT_LOGGED_IN=true"
if(-not $Install){
    Write-Host "QMT_FINANCIAL_DAILY_TASK_PREVIEW_ONLY; pass -Install explicitly"
    exit 0
}
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-NoProfile -ExecutionPolicy Bypass -File " + [char]34 + $runner + [char]34) -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At "23:15"
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 23)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "QMT local financial announcement-window incremental refresh; independent of purchased eight-cycle market updater" -ErrorAction Stop | Out-Null
Write-Host "QMT_FINANCIAL_DAILY_TASK_INSTALLED=$taskName"
