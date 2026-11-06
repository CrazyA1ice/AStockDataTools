# Verify the real 1990-2026 tiered daily read and cumulative minute progress.
# No new market Parquet/H5 written; the daily query has no OHLCVA in its log/SAFE.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$h=Join-Path $module 'reports\pre2011-day-historical-candidates-and-2011-2026-union-3c808c8da646.json'
$m=Join-Path $module 'reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json'
$modernSha='bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05'
foreach($f in @($py,$h,$m)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing $f"}
}
if ((Get-FileHash -LiteralPath $m -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modernSha) {
    throw 'Immutable 2011-2026 private day SHA changed'
}
$hsha=(Get-FileHash -LiteralPath $h -Algorithm SHA256).Hash.ToLowerInvariant()
$tests=@('test_query_private_1990_2026_tiered_day_local.py','test_report_verified_unified_minute_progress.py')
foreach($test in $tests){
    & $py -m unittest discover -s (Join-Path $module 'tests') -p $test -v
    if($LASTEXITCODE -ne 0){throw "Test failure: $test; no physical market writes"}
}
$id=[Guid]::NewGuid().ToString('N').Substring(0,12)
$dayOut=Join-Path $module "reports\tiered-private-day-read-smoke-$id.json"
& $py (Join-Path $module 'tools\query-private-1990-2026-tiered-day-local.py') --historical-version-safe $h --historical-version-sha256 $hsha --modern-version-safe $m --modern-version-sha256 $modernSha --symbol SH600000 --start 2010-12-28 --end 2011-01-06 --include-historical-hypothesis --max-result-bars 31 --out $dayOut --verify-local-private-only
if($LASTEXITCODE -ne 0){throw 'Bounded tiered local day query SHA/values failed, no production change'}
$day=Get-Content -LiteralPath $dayOut -Raw -Encoding UTF8|ConvertFrom-Json
if($day.status -ne 'local_optin_sha_pinned_1990_2026_tiered_day_read_not_production' -or
   $day.ready_for_production_query -ne $false -or
   $day.historical_vendor_units_or_stock_identity_certified -ne $false -or
   $day.safe_contains_private_licensed_bars_or_symbol -ne $false) {
    throw 'Private day local query misreported certification or exposed data'
}
$minuteOut=Join-Path $module "reports\verified-unique-minute-physical-progress-$id.json"
& $py (Join-Path $module 'tools\report-verified-unified-minute-progress.py') --out $minuteOut --verify-existing-sha-only
if($LASTEXITCODE -ne 0){throw 'Minute private Parquet complete-day SHA/duplicate audit failed'}
$minute=Get-Content -LiteralPath $minuteOut -Raw -Encoding UTF8|ConvertFrom-Json
if($minute.status -ne 'unique_minute_dates_existing_private_physical_parquet_sha_rechecked_not_full_history' -or
   $minute.all_historical_minute_days_completed -ne $false -or
   $minute.new_market_parquet_or_h5_written -ne $false) {
    throw 'Private minute status failed exact progress contract'
}
Write-Host "PASS: bounded 1990-2026 local historical/modern research DAY view; historical units remain UNVERIFIED"
Write-Host "DAY SAFE: $dayOut"
# A verified physical receipt is not necessarily net NEW source coverage.
# The retired minute GUI copied original purchased Parquet bars on prior dates.
# Report the SHA-verified private physical evidence and explicitly keep
# source-only H5 gap key counts UNKNOWN until an indexed source comparison.
$keys=@($minute.verified_unique_date_rows.PSObject.Properties.Name | Sort-Object)
if($keys.Count -ne [int]$minute.unique_nonempty_date_count){throw 'Minute physical receipt date-count conservation failed'}
$months=@($keys | ForEach-Object {$_.Substring(0,7)} | Group-Object | Sort-Object Name | ForEach-Object {"$($_.Name)=$($_.Count)"})
Write-Host "Minute SHA-verified private physical receipt dates: $($minute.unique_nonempty_date_count)"
Write-Host "Minute receipt span: $($minute.first_verified_day)..$($minute.last_verified_day)"
Write-Host "Minute receipt month counts: $($months -join ', ')"
Write-Host "Minute private PHYSICAL rows (NOT net new coverage): 1min=$($minute.verified_physical_rows_by_period.'1min') 5min=$($minute.verified_physical_rows_by_period.'5min') total=$($minute.verified_physical_rows_total)"
Write-Host 'Minute net new H5-only exact keys: NOT ESTABLISHED by physical receipt totals.'
Write-Host "MINUTE SAFE: $minuteOut"
Write-Host 'NEXT read-only key-delta source audit: H5ParquetReconciler/run-minute-jan2026-tail-index-audit.ps1 (2026-01-08..31).'
Write-Host 'DO NOT start the retired full-purchased-minute rewrite worker or GUI for bulk conversion.'
