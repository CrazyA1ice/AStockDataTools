# Explicit selected-stock QMT financial cache refresh, NOT database import.
param(
    [Parameter(Mandatory=$true)][string]$Symbols,
    [Parameter(Mandatory=$true)][string]$StartDate,
    [Parameter(Mandatory=$true)][string]$EndDate,
    [switch]$ExplicitCacheRefresh
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if(-not $ExplicitCacheRefresh){throw 'EXPLICIT_QMT_CACHE_REFRESH_OPTIN_REQUIRED'}
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
if(-not(Test-Path -LiteralPath (Join-Path $repo '.git') -PathType Container)){throw 'CANONICAL_CHECKOUT_REQUIRED'}
$python=Join-Path $repo '.venv\Scripts\python.exe'
$worker=Join-Path $module 'qmt_extra_financial_cache_worker.py'
$review=Join-Path $module 'market_scoped_finance_history_review.py'
if(-not(Test-Path -LiteralPath $python -PathType Leaf) -or -not(Test-Path -LiteralPath $worker -PathType Leaf) -or -not(Test-Path -LiteralPath $review -PathType Leaf)){throw 'FINANCE_WORKER_OR_COMPARATOR_MISSING'}
$codes=@($Symbols.Split(',') | ForEach-Object {$_.Trim()} | Where-Object {$_})
if($codes.Count -lt 1 -or $codes.Count -gt 5){throw 'SELECT_ONE_TO_FIVE_STOCKS'}
foreach($code in $codes){if($code -cnotmatch '^\d{6}\.(SH|SZ|BJ)$'){throw 'INVALID_STOCK_CODE'}}
$unique=@($codes | Sort-Object -Unique)
if($unique.Count -ne $codes.Count){throw 'DUPLICATED_FINANCIAL_STOCK'}
$codes=$unique
$start=[datetime]::MinValue
$end=[datetime]::MinValue
$culture=[System.Globalization.CultureInfo]::InvariantCulture
$style=[System.Globalization.DateTimeStyles]::None
if(-not [datetime]::TryParseExact($StartDate,'yyyy-MM-dd',$culture,$style,[ref]$start) -or -not [datetime]::TryParseExact($EndDate,'yyyy-MM-dd',$culture,$style,[ref]$end)){throw 'INVALID_DATE'}
if($start -gt $end -or ($end-$start).TotalDays -gt 30){throw 'WINDOW_EXCEEDS_31_DAYS'}
$zone=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$now=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$zone)
$minute=$now.Hour*60+$now.Minute
if($minute -ge 1190 -and $minute -lt 1225){throw 'SCHEDULED_2005_GUARD_WINDOW'}
$cutoff=$now.Date
if($minute -lt 1205){$cutoff=$cutoff.AddDays(-1)}
while($cutoff.DayOfWeek -eq [DayOfWeek]::Saturday -or $cutoff.DayOfWeek -eq [DayOfWeek]::Sunday){$cutoff=$cutoff.AddDays(-1)}
if($end -gt $cutoff){throw 'DATE_AFTER_SAFE_CUTOFF'}
$mutex=[System.Threading.Mutex]::new($false,'Local\AStockDataTools2005AllStages')
$held=$false
$jobDir=$null
$log=$null
try{
    try{$held=$mutex.WaitOne(0)}catch [System.Threading.AbandonedMutexException]{$held=$true}
    if(-not $held){throw 'DAILY_UPDATE_ALREADY_RUNNING'}
    $work=Join-Path $module 'work'
    $private=Join-Path $work 'qmt_extra'
    foreach($path in @($work,$private)){
        if(-not(Test-Path -LiteralPath $path -PathType Container)){throw 'CANONICAL_PRIVATE_WORKSPACE_MISSING'}
        if(((Get-Item -LiteralPath $path -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0){throw 'REDIRECTED_PRIVATE_WORKSPACE'}
    }
    $root=Join-Path $private 'scoped-cache-stage'
    if(-not(Test-Path -LiteralPath $root)){New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null}
    if(((Get-Item -LiteralPath $root -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0){throw 'REDIRECTED_SCOPED_STAGE'}
    $jobDir=Join-Path $root ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $jobDir -ErrorAction Stop | Out-Null
    $output=Join-Path $jobDir 'cache.json'
    $log=Join-Path $work ('afternoon-'+$now.ToString('yyyyMMdd-HHmmss')+'-SCOPED_FINANCE-'+[guid]::NewGuid().ToString('N')+'.log')
    $startLine='SCOPED_FINANCE_CACHE_START stock_count='+$codes.Count+' dates='+$StartDate+'..'+$EndDate
    Set-Content -LiteralPath $log -Value $startLine -Encoding UTF8 -ErrorAction Stop
    Write-Host $startLine
    $info=[System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$python
    $info.Arguments='-u -B "'+$worker+'" --symbols '+($codes -join ',')+' --output "'+$output+'" --mode daily --start '+$start.ToString('yyyyMMdd')+' --end '+$end.ToString('yyyyMMdd')
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$false
    $child=[System.Diagnostics.Process]::new()
    $child.StartInfo=$info
    try{
        if(-not $child.Start()){throw 'FINANCE_WORKER_START_FAILED'}
        if(-not $child.WaitForExit(300000)){
            $child.Kill()
            [void]$child.WaitForExit(5000)
            throw 'FINANCE_WORKER_TIMEOUT_300_SECONDS'
        }
        if($child.ExitCode -ne 0){throw ('FINANCE_WORKER_EXIT_'+$child.ExitCode)}
    }finally{$child.Dispose()}
    if(-not(Test-Path -LiteralPath $output -PathType Leaf)){throw 'FINANCE_WORKER_OUTPUT_MISSING'}
    $size=(Get-Item -LiteralPath $output -Force).Length
    if($size -lt 1 -or $size -gt 268435456){throw 'FINANCE_WORKER_OUTPUT_SIZE_INVALID'}
    $digest=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash
    $ledger=Join-Path $private 'financial-cache-progress.json'
    if(-not(Test-Path -LiteralPath $ledger -PathType Leaf)){throw 'CANONICAL_FINANCE_LEDGER_MISSING'}
    $ledgerSha=(Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash
    # Never pass raw records to the UI/log; precommit child reads the private
    # staged JSON and emits aggregate nine-table counts only.
    $audit=[System.Diagnostics.ProcessStartInfo]::new()
    $audit.FileName=$python
    $audit.Arguments='-u -B "'+$review+'" --root "D:\stock" --workspace "'+$private+'" --cache-file "'+$output+'" --expected-cache-sha256 '+$digest+' --expected-progress-sha256 '+$ledgerSha+' --symbols '+($codes -join ',')+' --start '+$start.ToString('yyyyMMdd')+' --end '+$end.ToString('yyyyMMdd')+' --explicit-readonly'
    $audit.UseShellExecute=$false
    $audit.CreateNoWindow=$true
    $audit.RedirectStandardOutput=$true
    $check=[System.Diagnostics.Process]::new()
    $check.StartInfo=$audit
    try{
        if(-not $check.Start()){throw 'PRECOMMIT_REVIEW_START_FAILED'}
        $readTask=$check.StandardOutput.ReadToEndAsync()
        if(-not $check.WaitForExit(90000)){
            $check.Kill()
            [void]$check.WaitForExit(5000)
            throw 'PRECOMMIT_REVIEW_TIMEOUT_90_SECONDS'
        }
        $summary=$readTask.GetAwaiter().GetResult()
        if($check.ExitCode -ne 0){throw ('PRECOMMIT_REVIEW_EXIT_'+$check.ExitCode)}
    }finally{$check.Dispose()}
    if($summary.Length -lt 10 -or $summary.Length -gt 65536){throw 'PRECOMMIT_REVIEW_RECEIPT_SIZE_INVALID'}
    try{$report=$summary | ConvertFrom-Json -ErrorAction Stop}
    catch{throw 'PRECOMMIT_REVIEW_RECEIPT_INVALID'}
    if($report.status -ne 'SCOPED_FINANCE_NINE_TABLE_PRECOMMIT_READONLY' -or
       $report.can_commit -ne $false -or
       $report.official_market_writes -ne 0 -or
       $report.financial_ledger_writes -ne 0 -or
       $report.qmt_calls -ne 0 -or
       $report.symbols_requested -ne $codes.Count){
        throw 'PRECOMMIT_REVIEW_EVIDENCE_REJECTED'
    }
    # Recheck both source files after the child exits; any concurrent
    # mutation refuses a clean receipt even when its own SHA checks passed.
    if((Get-FileHash -LiteralPath $ledger -Algorithm SHA256).Hash -ne $ledgerSha -or
       (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash -ne $digest){
        throw 'PRECOMMIT_REVIEW_EVIDENCE_CHANGED'
    }
    Add-Content -LiteralPath $log -Value @(
        'SCOPED_FINANCE_PRECOMMIT='+$summary.Trim(),
        'CANONICAL_PARQUET_COMMIT=NO',
        'MULTISOURCE_VERIFICATION=NOT_RUN') -Encoding UTF8
    Write-Host ('SCOPED_FINANCE_HISTORY_REVIEW stocks_with_conflict='+$report.stocks_history_conflict+' missing_cache='+$report.stocks_missing_cache+' new_version_candidates='+$report.stocks_candidate_for_review)
    $success='SCOPED_FINANCE_CACHE_READY stock_count='+$codes.Count+' bytes='+$size+' sha256='+$digest
    Add-Content -LiteralPath $log -Value $success -Encoding UTF8
    Write-Host $success
    Write-Host 'SCOPED_FINANCE_CANONICAL_PARQUET_UNCHANGED=TRUE'
    Write-Host 'SCOPED_FINANCE_HISTORY_REPAIR_APPROVED=FALSE'
}
catch{
    if($log){
        $message=([string]$_.Exception.Message -replace '[\r\n]',' ')
        Add-Content -LiteralPath $log -Value ('SCOPED_FINANCE_CACHE_FAILED='+$message.Substring(0,[math]::Min($message.Length,220))) -Encoding UTF8 -ErrorAction SilentlyContinue
    }
    throw
}
finally{
    if($jobDir -and (Test-Path -LiteralPath $jobDir)){Remove-Item -LiteralPath $jobDir -Recurse -Force}
    if($held){$mutex.ReleaseMutex()}
    $mutex.Dispose()
}
