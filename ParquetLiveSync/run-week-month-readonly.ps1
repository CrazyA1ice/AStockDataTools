# STRICTLY READ-ONLY audit of local purchased WEEK/MONTH vs verified DAY;
# zero real Parquet/H5 writes. Unit tests write only temporary synthetic data.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$folder=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $folder
$python=Join-Path $repo '.venv\Scripts\python.exe'
$script=Join-Path $folder 'rollup_week_month.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'Missing local ParquetLiveSync Python environment'}
if(-not (Test-Path -LiteralPath 'D:\stock\AllCycleAStockData\day\2026-10.parquet' -PathType Leaf)){throw 'Missing downloaded official TDX October physical DAY month'}
if(-not (Test-Path -LiteralPath 'D:\stock\AllCycleAStockData\day\2026-11.parquet' -PathType Leaf)){throw 'Missing downloaded official TDX November physical DAY month'}
Write-Host '===== 46 OFFLINE REAL TEMP ARROW ZIP/OHLCVA/TIMESTAMP/MONTH / YEAR TESTS ====='
& $python -B -m unittest discover -s (Join-Path $folder 'tests') -p 'test_*.py' -q
if($LASTEXITCODE -ne 0){throw 'Week/Month safety tests failed; no purchased market source written'}
Write-Host '===== PURCHASED 2026-05..09 WEEK/MONTH STRICT OHLCVA AND TIMESTAMP CALIBRATION ====='
& $python -B $script --root 'D:\stock'
if($LASTEXITCODE -ne 0){throw 'Local WEEK/MONTH convention not proved; no Week/Month Parquet source changed'}
Write-Host 'PASS_WEEK_MONTH_READONLY_CALIBRATION; NO_LOCAL_MARKET_FILE_WRITES=TRUE'
Write-Host 'Open ParquetLiveSync GUI to explicitly confirm writing fully closed weeks/months after this audit.'
