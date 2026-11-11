# First real additional Parquet-primary minute H5 write: 2026-09-24.
# Uses *accepted* 8-cycle physical source dataset SHA. Reuses original
# purchased Parquet in place, copies original 1min/5min H5 only once into
# six NEW isolated files, replaces matching H5 keys in copies, keeps all
# old-only records/tables. Does NOT overwrite D:\stock or existing day H5.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\mirror-asof20261013-purchased-minute-parquet-into-copied-native-h5.py'
$test='test_mirror_asof20261013_purchased_minute_parquet_into_copied_native_h5.py'
$sha='a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01'
$manifest=Join-Path $module 'work\unified_parquet\datasets\eight_cycle_asof_20261013_a4987bba0ce3a1f6\manifest.json'
$priorSafe=Join-Path $module 'reports\mixed-purchased-h5-native-minute-4days-660389198d64.json'
$priorDir=Join-Path $module 'work\h5_mirror\minute_union_660389198d64'
foreach($f in @($py,$tool,$manifest,$priorSafe)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw ('Missing existing eight-cycle source or real H5 writer: '+$f)}}
if(-not (Test-Path -LiteralPath $priorDir -PathType Container)){throw 'Previously accepted 6,427,013-row minute native H5 directory missing'}
Write-Host '==== SEVEN REAL SYNTHETIC PARQUET->ORIGINAL HIKYUU NATIVE H5 COPY TESTS ===='
& $py -B -m unittest discover -s (Join-Path $module 'tests') -p $test -q
if($LASTEXITCODE -ne 0){throw 'Minute H5 original-preserving Parquet source test failed before real market writes'}
$rid=[Guid]::NewGuid().ToString('N').Substring(0,12)
$safe=Join-Path $module ("reports\purchased-minute-native-h5-copy-20260924-$rid.json")
Write-Host '==== REAL 2026-09-24 PURCHASED PARQUET -> SIX COPIED H5 1min/5min SOURCES ===='
& $py -B $tool --root 'D:\stock' --manifest $manifest --dataset-sha256 $sha --from-day '2026-09-24' --through-day '2026-09-24' --run-id $rid --out $safe --max-source-rows 4000000 --prior-four-day-native-safe $priorSafe --prior-four-day-native-root $priorDir --write-isolated-minute-h5
if($LASTEXITCODE -ne 0){throw 'Real 2026-09-24 1min/5min Parquet->native copied H5 refused; original market unchanged'}
if(-not (Test-Path -LiteralPath $safe -PathType Leaf)){throw 'Missing accepted native purchased minute H5 receipt'}
$r=Get-Content -LiteralPath $safe -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.status -ne 'purchased_2026_september_bounded_native_1m5m_H5_copy_merged_verified' -or $r.physical_dataset_sha256 -ne $sha -or $r.window[0] -ne '2026-09-24' -or $r.window[1] -ne '2026-09-24' -or $r.native_h5_files -ne 6 -or $r.prior_four_day_native_mirror_reused_not_reconverted -ne $true -or [long]$r.already_written_prior_four_day_native_rows_reused.'1min' -ne 5358629 -or [long]$r.already_written_prior_four_day_native_rows_reused.'5min' -ne 1068384 -or @($r.new_native_h5_files_sha256.PSObject.Properties).Count -ne 6 -or $r.native_minute_table_40byte_all_changed_stock_integer_readback_verified -ne $true -or $r.all_original_H5_files_copied_and_untouched -ne $true -or $r.original_purchased_parquet_files_unmodified -ne $true -or $r.purchase_numeric_units_and_time_labels_vendor_certified -ne $false -or $r.whole_history_H5_completed -ne $false -or $r.production_H5_activated -ne $false -or [long]$r.purchased_parquet_source_rows_written_as_native_h5.'1min' -le 0 -or [long]$r.purchased_parquet_source_rows_written_as_native_h5.'5min' -le 0){throw 'Real native minute H5 purchased-primary source/copy integer acceptance failed'}
Write-Host ('PASS_FIRST_REAL_PARQUET_TO_NATIVE_MINUTE_H5_ASOF_20261013 PRIOR_FOUR_DAY_NATIVE_1MIN=5358629 PRIOR_FOUR_DAY_NATIVE_5MIN=1068384 NEW_PURCHASED_1MIN='+$r.purchased_parquet_source_rows_written_as_native_h5.'1min'+' 5min='+$r.purchased_parquet_source_rows_written_as_native_h5.'5min'+' ORIGINAL_H5_WRITES=0')
Write-Host ('NEW_ISOLATED_1MIN_5MIN_H5='+ (Join-Path $module ("work\h5_mirror\minute_purchased_wave_$rid")))
Write-Host ('MINUTE_H5_SAFE='+$safe)
