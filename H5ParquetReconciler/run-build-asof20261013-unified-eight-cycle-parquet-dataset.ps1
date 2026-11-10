# Build one immutable, actually openable PyArrow Parquet FILE dataset
# spanning all eight cycles through 2026-10-13, no paid Parquet copying.
# 1990-2010 historical H5 candidate is a SEPARATE research layer.
# Nothing from Oct 14-31 is requested, staged, or marked missing.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\build-asof20261013-unified-eight-cycle-parquet-dataset.py'
$catalog='7f4a84f07d519e317d6b51049004d937acd8cba4cf561a3312fe457c5bed68df'
$modern='bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05'
$daySafe=Join-Path $module 'reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json'
foreach($path in @($py,$tool,$daySafe)){
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){
        throw ('Existing verified physical dataset source missing: '+$path)
    }
}
# Existing two source registries and one new all-eight Arrow physical proof.
foreach($pattern in @(
    'test_build_purchased_primary_eight_cycle_private_source_catalog.py',
    'test_query_catalog_bound_purchased_primary_eight_cycles_readonly.py',
    'test_build_asof20261013_unified_eight_cycle_parquet_dataset.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Physical Parquet dataset regression failed: '+$pattern)}
}
Write-Host '===== BUILD REAL PURCHASED-PRIMARY EIGHT-CYCLE PARQUET DATASET FILE GRAPH ====='
# Existing paid original data remains unmodified, so constructing this Arrow
# dataset does not duplicate millions of rows or create hard/symbolic links.
& $py -B $tool --root 'D:\stock' --source-catalog-sha256 $catalog --modern-day-version-sha256 $modern --modern-day-version-safe $daySafe | Tee-Object -Variable lines
if($LASTEXITCODE -ne 0){throw 'Physical 1990-2026 existing-source Parquet dataset build failed closed'}
$selected=@($lines | Where-Object {$_ -like 'UNIFIED_20261013_EIGHT_CYCLE_PARQUET_DATASET=*'})
if($selected.Count -ne 1){throw 'Missing exactly one physical eight-cycle dataset safe result'}
$j=([string]$selected[0]).Substring('UNIFIED_20261013_EIGHT_CYCLE_PARQUET_DATASET='.Length) | ConvertFrom-Json
if($j.status -ne 'purchased_primary_asof_20261013_eight_cycle_physical_parquet_file_dataset_v1' -or $j.dataset_sha256 -notmatch '^[a-f0-9]{64}$' -or $j.manifest_relative_file -notmatch '^work/unified_parquet/datasets/eight_cycle_asof_20261013_[a-f0-9]{16}/manifest\.json$' -or $j.actual_pyarrow_datasets_opened -ne 8 -or $j.all_eight_cycles_physically_addressable -ne $true -or @($j.file_count_by_period.PSObject.Properties).Count -ne 8 -or @($j.arrow_fragment_counts.PSObject.Properties).Count -ne 8 -or $j.modern_day_physical_rows -ne 14137981 -or $j.h5_gap_day_rows -ne 22274 -or $j.h5_derived_highcycle_candidate_rows -ne 621348 -or $j.historical_research_files -ne 21 -or $j.historical_research_rows_not_in_modern_standard_day -ne 3682327 -or $j.market_data_copied -ne $false -or $j.original_market_files_modified -ne $false -or $j.ready_for_production_query -ne $false -or $j.market_bar_batches_read_during_arrow_open -ne $false){throw 'Eight-cycle physical Parquet data/file conservation or safety gate failed'}
$manifest=Join-Path $module ($j.manifest_relative_file.Replace('/','\'))
if(-not (Test-Path -LiteralPath $manifest -PathType Leaf)){throw 'Immutable dataset physical fragment manifest not created'}
$record=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
if($record.dataset_sha256 -ne $j.dataset_sha256 -or $record.payload.source_catalog_sha256 -ne $catalog -or $record.payload.modern_16year_day_physical_version_sha256 -ne $modern -or $record.payload.asof_inclusive -ne '2026-10-13' -or $record.payload.strict_cutoff_next_day -ne '2026-10-14' -or $record.payload.historical_1990_2010_day.included_as_standard_day -ne $false -or $record.payload.historical_1990_2010_day.historical_source_staged_and_sha_validated -ne $true -or $record.payload.no_purchased_parquet_copy -ne $true -or $record.payload.ready_for_production_query -ne $false -or $record.payload.ready_for_h5_mirror -ne $false -or $record.payload.full_market_completeness_certified -ne $false -or $record.payload.original_market_files_modified -ne $false -or $record.payload.active_pointer_modified -ne $false){throw 'Physical Parquet manifest has unsafe provenance'}
$counts=$j.file_count_by_period.PSObject.Properties | Sort-Object Name
foreach($v in $counts){if([int]$v.Value -le 0){throw ('Missing physical Arrow Parquet files for '+$v.Name)};Write-Host ('PARQUET_DATASET_PERIOD='+$v.Name+' PHYSICAL_FILES='+$v.Value)}
Write-Host ('PASS_ASOF_20261013_ALL_EIGHT_CYCLE_REAL_PARQUET_DATASETS SHA256='+$j.dataset_sha256+' MODERN_DAY_ROWS=14137981 H5_DERIVED_HIGHCYCLE_ROWS=621348 HISTORICAL_RESEARCH_ONLY_ROWS=3682327 ORIGINAL_PURCHASED_COPIES=0 PRODUCTION_MERGED=FALSE')
Write-Host ('UNIFIED_DATASET_MANIFEST='+$manifest)
