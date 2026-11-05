# Exact 2025 purchased source code timeline: 300114 to 302132.
# Issuer's 2025-02-14 announcement confirms change effective 2025-02-17.
# Source-only 5min ts/symbol scan; NO automatic A-share alias/mapping.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-purchased-2025-302132-code-transition-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing source transition audit requirement: $f"}}
& $py -B -m unittest discover -s $tests -p 'test_audit_purchased_2025_302132_code_transition_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Synthetic code change timeline tests failed; no real market source opened'}
Write-Host '===== 2025 purchased source-key-only issuer change audit ====='
$rows=@(& $py -B $tool --root 'D:\stock' --max-source-rows 70000000)
$exit=$LASTEXITCODE
if($exit -ne 0){$rows | Out-Host;throw 'Official code transition source audit failed; source files unchanged'}
$report=($rows -join [Environment]::NewLine) | ConvertFrom-Json
if($report.status -ne '2025_300114_302132_source_label_timeline_audited_not_mapped' -or $report.scanned_2025_5min_source_rows -ne 64081920 -or $report.sz302_prefix_actual_source_stockdays -ne 243 -or $report.sz302_prefix_actual_source_rows -ne 11664 -or $report.source_ohlcva_read -ne $false -or $report.h5_source_bars_read -ne $false -or $report.original_market_files_modified -ne $false -or $report.private_stockday_index_written -ne $false -or $report.production_query_activated -ne $false -or $report.A_share_alias_auto_applied -ne $false){throw '2025 source code transition count/safety gate failed'}
foreach($row in $report.target_security_code_evidence.PSObject.Properties){
    $code=$row.Name
    $x=$row.Value
    if($x.nonstandard_48_key_stockdays -ne 0){throw "Nonstandard source time-grid for $code"}
    Write-Host ("SOURCE_CODE="+$code+" OBSERVED_DAYS="+$x.observed_stockdays+" BARS="+$x.five_minute_source_rows+" FIRST="+$x.earliest_day+" LAST="+$x.latest_day+" BEFORE_2025_02_17="+$x.before_official_effective_stockdays+" ON_OR_AFTER="+$x.after_or_on_official_effective_stockdays)
}
Write-Host ("OFFICIAL_CHANGE=SZ300114_TO_SZ302132 EFFECTIVE="+$report.official_code_change_day+" HISTORICAL_NEW_CODE_EARLY_DAYS="+$report.src_302132_pre_effective_history_stockdays+" OLD_NEW_SAME_DAY="+$report.old_new_same_date_stockdays+" VENDOR_HISTORIC_CODE_REWRITE_SUSPECTED="+$report.historical_new_code_present_before_official_code_change)
Write-Host 'PASS: original 2025 purchased 5min issuer-code timeline audited; NO automatic renaming, A-share filter expansion, index or market-data writes.'
