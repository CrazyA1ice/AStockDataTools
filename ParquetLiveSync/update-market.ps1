param(
    [ValidateSet("auto","bootstrap","daily")]
    [string]$Mode = "auto",
    [string]$Root = "D:\stock",
    [string]$Day = "",
    [string]$Config = "",
    [ValidateRange(1,30)]
    [int]$MaxDays = 30,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Missing project Python .venv" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "MARKET_UPDATE_ONE_COMMAND mode=$Mode dry_run=$DryRun"
& $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_market_updater.py" -q
if ($LASTEXITCODE -ne 0) { throw "Market updater synthetic safety tests failed" }
$a = @("-u","-B","ParquetLiveSync\update_market.py","--mode",$Mode,"--root",$Root,"--max-days",[string]$MaxDays)
if ($Day) { $a += @("--day",$Day) }
if ($Config) { $a += @("--config",$Config) }
elseif (Test-Path -LiteralPath "ParquetLiveSync\\work\\market_update\\sources.local.json" -PathType Leaf) {
    $a += @("--config","ParquetLiveSync\\work\\market_update\\sources.local.json")
}
if ($DryRun) { $a += "--dry-run" }
& $python @a
if ($LASTEXITCODE -ne 0) { throw "Market updater did not complete; source and transactional state retained" }
Write-Host "MARKET_UPDATE_ONE_COMMAND_SUCCESS"
