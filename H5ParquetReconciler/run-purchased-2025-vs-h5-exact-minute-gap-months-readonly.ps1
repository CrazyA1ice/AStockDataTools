# Reuse ACCEPTED purchased 2025 monthly grid receipts and completed source indexes.
# H5 exact 1m/5m key differences ONLY. No Parquet/H5 writes, no new indexes.
# At most TWO 2025 months each invocation; source data is never copied.
param([string]$FromMonth='2025-01',[string]$ThroughMonth='2025-02')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-2025-purchased-h5-exact-minute-gap-months-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing read-only 2025 source-gap prerequisite: $f"}
}
Write-Host '===== 10 synthetic fail-closed 2025 purchased/H5 exact monthly gap tests ====='
& $py -B -m unittest discover -s $tests -p 'test_audit_2025_purchased_h5_exact_minute_gap_months_readonly.py' -q
if($LASTEXITCODE -ne 0){throw '2025 exact H5 monthly gap tests FAILED: market audit not started'}
Write-Host ("===== REAL PURCHASED-FIRST H5 EXACT KEY AUDIT "+$FromMonth+".."+$ThroughMonth+" =====")
$lines=@()
& $py -B $tool --root 'D:\stock' --from-month $FromMonth --through-month $ThroughMonth | Tee-Object -Variable lines
if($LASTEXITCODE -ne 0){throw 'H5 minute exact-key audit FAILED: no market files written'}
$summary=@($lines|Where-Object {$_ -like 'H5_2025_EXACT_MONTH_GAP_SUMMARY=*'})
if($summary.Count -ne 1){throw 'Missing single complete 2025 H5 source-gap audit result'}
$obj=([string]$summary[0]).Substring('H5_2025_EXACT_MONTH_GAP_SUMMARY='.Length)|ConvertFrom-Json
if($obj.status -ne '2025_purchased_first_h5_exact_minute_gaps_candidate_readonly_not_activated' -or $obj.all_purchased_month_grid_receipts_preverified_and_reused -ne $true -or $obj.all_source_key_indexes_existing_and_reused -ne $true -or $obj.new_source_key_indexes_created -ne 0 -or $obj.purchased_ohlcva_read_or_copied -ne $false -or $obj.original_purchased_parquet_or_h5_modified -ne $false -or $obj.h5_candidate_keys_automatically_accepted -ne 0 -or $obj.new_market_parquet_or_h5_written -ne $false -or $obj.source_fingerprint_is_content_sha -ne $false -or $obj.production_activated -ne $false -or $obj.ready_for_production_query -ne $false){throw 'H5 source-gap audit has violated strict source/read-only contracts'}
foreach($period in @('1min','5min')){
    $x=$obj.summaries.PSObject.Properties[$period].Value
    Write-Host ('AUDITED_'+$period+' PURCHASED_KEYS='+$x.purchased_a_share_date_key_count+' H5_FULL_CANDIDATE_KEYS='+$x.h5_only_keys_on_full_purchased_absence_days+' H5_PARTIAL_CANDIDATE_KEYS='+$x.h5_only_candidate_keys_on_partial_purchased_stockdays+' H5_ACCEPTED_KEYS=0')
}
Write-Host ('PASS_2025_H5_EXACT_MINUTE_GAP_CANDIDATES_READONLY MONTHS='+$obj.months_audited+' PRIVATE_INDEXES_NEW=0 PRODUCTION_MERGED=FALSE')
