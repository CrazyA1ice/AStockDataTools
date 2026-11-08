# 2011..2026 purchased-source 8-cycle FOOTER inventory. NO OHLCVA reads.
# Uses existing safe footer survey; no originals, indexes or market files written.
# This is named-year/source-time ENVELOPE only, NOT per-security exact coverage.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$script=Join-Path $module 'tools\survey-purchased-all-cycle-footers-readonly.py'
$test=Join-Path $module 'tests'
foreach($f in @($py,$script)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){
        throw "Missing historical source footer inventory prerequisite: $f"
    }
}
& $py -B -m unittest discover -s $test -p 'test_survey_purchased_all_cycle_footers_readonly.py' -q
if($LASTEXITCODE -ne 0){throw 'Source-only footer inventory synthetic tests FAILED'}
$years=@(2011..2026)
$raw=@(& $py -B $script --root 'D:\stock' --years $years --max-total-files 5000 --max-row-groups-per-year-period 100000)
if($LASTEXITCODE -ne 0){throw 'Original purchased 2011-2026 footer survey FAILED; no market writes'}
$report=($raw -join [Environment]::NewLine) | ConvertFrom-Json
if($report.status -ne 'read_only_purchased_parquet_footer_envelopes_not_exact_coverage' -or $report.only_original_parquet_file_footers_read -ne $true -or $report.no_ohlcva_rows_read_or_exported -ne $true -or $report.original_h5_opened -ne $false -or $report.original_market_files_modified -ne $false -or $report.new_market_or_index_files_written -ne $false -or $report.production_pointer_modified -ne $false -or $report.actual_stockday_and_full_exchange_calendar_coverage_certified -ne $false -or $report.timestamp_and_vendor_physical_unit_semantics_certified -ne $false -or $report.noncanonical_directory_names_not_automatically_mapped -ne $true){
    throw 'Unsafe or overclaimed 2011-2026 footer source report'
}
if((@($report.requested_years) -join ',') -ne ($years -join ',')){throw 'Wrong requested historical year window'}
$periods=@('1min','5min','15min','30min','60min','day','week','month')
foreach($period in $periods){
    $item=$report.period_years.PSObject.Properties[$period]
    if($null -eq $item){throw "Missing canonical purchased K-line folder: $period"}
    $annual=$item.Value
    $rows=[decimal]0
    $files=0
    $groups=0
    $missing=@()
    $present=@()
    $unknown=0
    $outOfYear=0
    $first=$null
    $last=$null
    foreach($year in $years){
        $field=$annual.PSObject.Properties[[string]$year]
        if($null -eq $field){throw "Missing source year entry: $period $year"}
        $x=$field.Value
        if($x.source_files -eq 0){
            $missing+=([string]$year)
            continue
        }
        $present+=([string]$year)
        $files+=[int]$x.source_files
        $rows+=[decimal]$x.source_rows_from_parquet_footers
        $groups+=[int]$x.row_groups
        $unknown+=[int]$x.nonempty_row_groups_without_usable_ts_bounds
        $outOfYear+=[int]$x.row_groups_with_bounds_outside_filename_year
        if($null -ne $x.earliest_known_raw_beijing_timestamp){
            $stamp=[string]$x.earliest_known_raw_beijing_timestamp
            if($null -eq $first -or [string]::CompareOrdinal($stamp,$first) -lt 0){$first=$stamp}
        }
        if($null -ne $x.latest_known_raw_beijing_timestamp){
            $stamp=[string]$x.latest_known_raw_beijing_timestamp
            if($null -eq $last -or [string]::CompareOrdinal($stamp,$last) -gt 0){$last=$stamp}
        }
    }
    $missingText=if($missing.Count){$missing -join ','}else{'NONE'}
    Write-Host ('PURCHASED_FOOTER PERIOD='+$period+' NAMED_YEARS='+$present.Count+'/16 FILES='+$files+' ROWS_FROM_FOOTERS='+$rows+' ROWGROUPS='+$groups+' EARLIEST='+$first+' LATEST='+$last+' MISSING_NAMED_YEARS='+$missingText+' UNKNOWN_TS_ROWGROUPS='+$unknown+' OUTSIDE_NAMED_YEAR_ROWGROUPS='+$outOfYear+' EXACT_STOCKDAY_CERTIFIED=FALSE')
}
$unknownCycles=@($report.noncanonical_period_directory_labels_semantics_unverified)
if($unknownCycles.Count -gt 0){Write-Host ('UNMAPPED_NONKLINE_FOLDERS='+($unknownCycles -join ',')+' SEMANTICS_UNVERIFIED=TRUE')}
Write-Host ('SOURCE_FILE_NAMING_CAVEATS_JSON='+($report.file_naming_caveats|ConvertTo-Json -Depth 8 -Compress))
Write-Host ('PASS_2011_2026_EIGHT_CYCLE_ORIGINAL_PARQUET_FOOTER_INVENTORY SOURCE_YEAR_ENVELOPES_ONLY=TRUE PURCHASED_OHLCVA_COPIED=0 PRODUCTION_MERGED=FALSE')
