# Read-only recovery of October 13 16-stock HIGH-CYCLE private batch already written
# before an optional StrictMode inventory summary failed. Do NOT restage it.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\verify-existing-oct-high-cycle-private-batch-readonly.py'
$test=Join-Path $module 'tests'
foreach($p in @($py,$tool)){if(-not (Test-Path -LiteralPath $p -PathType Leaf)){throw ('Missing read-only existing stage verifier: '+$p)}}
& $py -B -m unittest discover -s $test -p 'test_verify_existing_oct_high_cycle_private_batch_readonly.py' -q
if($LASTEXITCODE -ne 0){throw 'Existing stage verification synthetic tests failed: do not restage'}
$known15='4a74862a12ea53355b67c34832d5aba19ca89a8441d4e1fdb2bf2df2527bc4db'
$known30='4b811f364ff378e55999b32680162dce2f8ff5fb881da7d50f05864800430178'
$known60='4fa0807499725b965eca3db4a1b782961c2c83a7f41ca3f7863798fda9530490'
$lines=@(& $py -B $tool --root 'D:\stock' --expected-15min-sha256 $known15 --expected-30min-sha256 $known30 --expected-60min-sha256 $known60 --verify-existing-only)
if($LASTEXITCODE -ne 0){throw 'Existing private batch did not pass read-only verification'}
$matches=@($lines|Where-Object {$_ -like 'PRIVATE_OCT_HIGH_CYCLE_EXISTING_VERIFY=*'})
if($matches.Count -ne 1){throw 'Missing unique read-only existing batch SAFE summary'}
$j=([string]$matches[0]).Substring('PRIVATE_OCT_HIGH_CYCLE_EXISTING_VERIFY='.Length)|ConvertFrom-Json
if($j.status -ne 'verified_existing_oct_13_private_high_cycle_batch_readonly' -or $j.day -ne '2026-10-13' -or $j.run_id -notmatch '^[a-f0-9]{12}$' -or $j.verified_source_stockdays -ne 16 -or $j.total_rows -ne 448 -or $j.original_market_files_modified -ne $false -or $j.new_private_or_production_files_written -ne $false -or $j.production_activated -ne $false -or $j.ready_for_production_merge -ne $false -or $j.independent_vendor_units_certified -ne $false -or $j.full_row_by_row_rederived_readback -ne $true -or $j.market_OHLCVA_not_printed -ne $true){throw 'Unsafe existing private batch verification summary'}
foreach($period in @('15min','30min','60min')){
    if($period -eq '15min'){$expectedRows=256;$expectedSHA=$known15}elseif($period -eq '30min'){$expectedRows=128;$expectedSHA=$known30}else{$expectedRows=64;$expectedSHA=$known60}
    $actualSHA=$j.outputs_sha256.PSObject.Properties[$period].Value
    $actualRows=$j.period_rows.PSObject.Properties[$period].Value
    if($actualRows -ne $expectedRows -or $actualSHA -ne $expectedSHA){throw 'Recovered Parquet output size/hash incorrect'}
    $file=Join-Path $module ('work\unified_parquet\oct_high_cycle_staging\'+$j.run_id+'\'+$period+'.parquet')
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw 'Recovered private Parquet missing'}
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedSHA){throw 'Recovered Parquet physical SHA does not match'}
    Write-Host ('RECOVERED_OCT_13_PERIOD='+$period+' ROWS='+$actualRows+' SHA256='+$actualSHA)
}
$receipt=Join-Path $module ('work\unified_parquet\oct_high_cycle_staging\'+$j.run_id+'\receipt.json')
if($j.receipt_relative_file -ne ('work/unified_parquet/oct_high_cycle_staging/'+$j.run_id+'/receipt.json') -or -not (Test-Path -LiteralPath $receipt -PathType Leaf)){throw 'Unexpected recovered receipt path'}
Write-Host ('PASS_OCT_13_EXISTING_16_STOCK_PRIVATE_HIGH_CYCLE_READONLY RUN_ID='+$j.run_id+' TOTAL_ROWS=448 NEW_FILES=0 ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
Write-Host ('PRIVATE_RECEIPT='+$receipt)
