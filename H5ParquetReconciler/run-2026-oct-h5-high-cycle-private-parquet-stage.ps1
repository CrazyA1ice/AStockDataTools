# Isolated private 2026 October 5m->15/30/60m candidate Parquet stage.
# Source receipts must be SHA-verified; purchased high cycles always win.
# NO original market writes, NO private/production pointer changes, NO H5 mirror.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\stage-2026-oct-verified-h5-high-cycle-private-parquet.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing private candidate stage prerequisite: $f"}}
foreach($pattern in @('test_audit_2026_oct_h5_five_minute_high_cycle_candidates_readonly.py','test_stage_2026_oct_verified_h5_high_cycle_private_parquet.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw "Private candidate materialization synthetic gate failed: $pattern"}
}
$rid=[Guid]::NewGuid().ToString('N').Substring(0,12)
$lines=@(& $py -B $tool --root 'D:\stock' --run-id $rid --write-private-candidates-only)
if($LASTEXITCODE -ne 0){throw 'Bounded private high-cycle stage FAILED; original market not modified'}
$line=@($lines|Where-Object {$_ -like 'PRIVATE_OCT_HIGH_CYCLE_STAGE=*'})
if($line.Count -ne 1){throw 'Missing unique private high-cycle stage SAFE response'}
$safe=([string]$line[0]).Substring('PRIVATE_OCT_HIGH_CYCLE_STAGE='.Length)|ConvertFrom-Json
$wanted=@('2026-10-08','2026-10-09','2026-10-12','2026-10-13')
if($safe.status -ne 'research_only_private_oct_h5_5min_highcycle_candidates_written_readback' -or $safe.run_id -ne $rid -or $safe.verified_source_stockdays -ne 8 -or (@($safe.source_days) -join ',') -ne ($wanted -join ',') -or (@($safe.symbols) -join ',') -ne 'SH600000,SZ000001' -or @($safe.sources).Count -ne 4 -or $safe.purchased_high_cycle_source_blocks -ne 0 -or $safe.source_5min_original_SHA_receipts_verified -ne $true -or $safe.all_48_native_start_grid_bars_required -ne $true -or $safe.all_purchased_high_cycle_periods_must_be_absent -ne $true -or $safe.no_day_week_month_materialized -ne $true -or $safe.vendor_physical_units_certified -ne $false -or $safe.timestamp_conversion_certified -ne $false -or $safe.corporate_adjustments_certified -ne $false -or $safe.original_market_files_modified -ne $false -or $safe.production_or_private_active_pointer_modified -ne $false -or $safe.ready_for_production_merge -ne $false -or $safe.ready_for_h5_mirror -ne $false -or $safe.raw_OHLCVA_in_report -ne $false){throw 'Unsafe private high-cycle Parquet stage SAFE response'}
$expected=@{'15min'=128;'30min'=64;'60min'=32}
foreach($period in @('15min','30min','60min')){
    $out=$safe.outputs.PSObject.Properties[$period].Value
    $relative='work/unified_parquet/oct_high_cycle_staging/'+$rid+'/'+$period+'.parquet'
    if($null -eq $out -or $out.rows -ne $expected[$period] -or $out.private_file -ne $relative -or $out.complete_row_by_row_readback_exact -ne $true -or $out.sha256 -notmatch '^[a-f0-9]{64}$'){throw 'Incorrect private candidate row count, path or readback'}
    $target=Join-Path $module ($out.private_file.Replace('/','\'))
    if(-not (Test-Path -LiteralPath $target -PathType Leaf)){throw "Missing private candidate Parquet: $period"}
    $actual=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if($actual -ne $out.sha256){throw 'Private candidate SHA changed after Python readback'}
    Write-Host ('PRIVATE_OCT_HIGH_CYCLE_PERIOD='+$period+' ROWS='+$out.rows+' PARQUET_SHA256='+$out.sha256+' PRODUCTION_MERGED=FALSE')
}
$receipt=Join-Path $module ('work\unified_parquet\oct_high_cycle_staging\'+$rid+'\receipt.json')
if(-not (Test-Path -LiteralPath $receipt -PathType Leaf)){throw 'Missing private candidate receipt'}
$readback=Get-Content -LiteralPath $receipt -Encoding UTF8 -Raw|ConvertFrom-Json
if($readback.run_id -ne $rid -or $readback.status -ne $safe.status -or $readback.verified_source_stockdays -ne 8){throw 'Private receipt identity did not match SAFE'}
Write-Host ('PASS_OCT_2026_PRIVATE_15_30_60MIN_PARQUET_STAGE RUN_ID='+$rid+' TOTAL_ROWS=224 SOURCE_STOCKDAYS=8 ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_ACTIVATED=FALSE')
Write-Host ('PRIVATE_RECEIPT='+$receipt)
