# Purchased eight-cycle original file references + SHA-verified four-day
# 1/5min H5 gap + 15/30/60m high-cycle candidate CATALOG ONLY.
# No original market copies, no indexes/active pointers/production merges.
param([switch]$PreviewOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\build-purchased-primary-eight-cycle-private-source-catalog.py'
$tests=Join-Path $module 'tests'
foreach($path in @($py,$tool)){if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw ('Missing source catalog prerequisite: '+$path)}}
foreach($pattern in @(
    'test_query_purchased_primary_with_private_highcycle_readonly.py',
    'test_build_purchased_primary_eight_cycle_private_source_catalog.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Source catalog safety regression failed: '+$pattern)}
}
$mode=if($PreviewOnly){'--preview-only'}else{'--write-private-catalog-only'}
$lines=@(& $py -B $tool --root 'D:\stock' $mode)
if($LASTEXITCODE -ne 0){throw 'Original Parquet/H5 source catalog validation failed'}
$report=@($lines|Where-Object {$_ -like 'PURCHASED_PRIMARY_EIGHT_CYCLE_SOURCE_CATALOG=*'})
if($report.Count -ne 1){throw 'Missing one purchased-primary catalog SAFE summary'}
$j=([string]$report[0]).Substring('PURCHASED_PRIMARY_EIGHT_CYCLE_SOURCE_CATALOG='.Length)|ConvertFrom-Json
if($j.status -ne 'purchased_primary_eight_cycle_private_source_references_only_v1' -or $j.purchased_years -ne 16 -or $j.purchased_periods -ne 8 -or $j.purchased_source_files -ne 192 -or $j.highcycle_candidate_stockdays -ne 22191 -or $j.highcycle_candidate_rows -ne 621348 -or $j.h5_private_minute_refs -ne 8 -or $j.catalog_sha256 -notmatch '^[a-f0-9]{64}$' -or $j.production_activated -ne $false -or $j.ready_for_production_merge -ne $false -or $j.original_market_files_modified -ne $false -or $j.purchased_parquet_bars_copied -ne $false -or $j.vendor_units_certified -ne $false -or $j.preview_only -ne [bool]$PreviewOnly){throw 'Untrusted purchased-primary source catalog summary'}
if($PreviewOnly){
    if($j.new_metadata_catalog_written -ne $false){throw 'Read-only preview unexpectedly wrote catalog'}
    Write-Host ('PASS_PURCHASED_PRIMARY_SOURCE_CATALOG_PREVIEW SHA256='+$j.catalog_sha256+' ORIGINAL_PURCHASED_FILES='+$j.purchased_source_files+' HIGHCYCLE_ROWS='+$j.highcycle_candidate_rows+' NEW_FILES=0')
    return
}
if($j.catalog_relative_file -ne ('work/unified_parquet/source_catalog/catalog_'+$j.catalog_sha256+'.json')){throw 'Unexpected versioned source catalog path'}
$file=Join-Path $module ($j.catalog_relative_file.Replace('/','\'))
if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw 'Versioned private source catalog missing'}
$sealed=Get-Content -LiteralPath $file -Encoding UTF8 -Raw|ConvertFrom-Json
if($sealed.catalog_sha256 -ne $j.catalog_sha256 -or $sealed.payload.status -ne $j.status -or $sealed.payload.ready_for_production_merge -ne $false -or $sealed.payload.original_market_files_modified -ne $false -or $sealed.payload.market_OHLCVA_read_or_copied_for_catalog -ne $false -or $sealed.payload.purchased.purchased_source_files_copied -ne $false -or $sealed.payload.private_research_candidates.highcycle_total_candidate_rows -ne 621348){throw 'Private source catalog receipt not safe'}
Write-Host ('PASS_PURCHASED_PRIMARY_EIGHT_CYCLE_PRIVATE_SOURCE_CATALOG SHA256='+$j.catalog_sha256+' ORIGINAL_PURCHASED_FILES_REFERENCED='+$j.purchased_source_files+' SHA_VERIFIED_HIGHCYCLE_ROWS='+$j.highcycle_candidate_rows+' MINUTE_H5_GAP_REFS='+$j.h5_private_minute_refs+' MARKET_ROWS_COPIED=0 PRODUCTION_MERGED=FALSE')
Write-Host ('PRIVATE_SOURCE_CATALOG='+$file)
