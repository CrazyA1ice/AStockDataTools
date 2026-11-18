# Native STDERR must never be mistaken for a failed QMT data stage.
# Pure PowerShell mock: no scheduled tasks, QMT or market data writes.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSScriptRoot
$runner=Join-Path $module 'scheduled-afternoon-update.ps1'
$t=$null
$parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    $runner,[ref]$t,[ref]$parseErrors)
if(@($parseErrors).Count -gt 0){throw 'Runner syntax error'}
$definition=$ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-MarketStage'
},$true)
if($null -eq $definition){throw 'Stage function missing'}
Invoke-Expression $definition.Extent.Text
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$temp=Join-Path ([IO.Path]::GetTempPath()) ('qmt-stage-stderr-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
try{
    $work=$temp
    $chinaNow=Get-Date
    $completed=New-Object System.Collections.ArrayList
    $failures=New-Object System.Collections.ArrayList
    $stageRecords=[ordered]@{}
    $success=Join-Path $temp 'success.ps1'
    [IO.File]::WriteAllText($success,@'
[Console]::Error.WriteLine("QMT_CACHE_WORKER_UTF8_DECODE_ERROR=retryable test diagnostic")
[Console]::Error.WriteLine("----------------------------------------------------------------------")
Write-Output 'MARKET_QMT_EXTRA_SUMMARY={"status":"BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN"}'
exit 0
'@)
    Invoke-MarketStage -Label 'SECTORS' -Script $success -Arguments @()
    if($completed.Count -ne 1 -or $failures.Count -ne 0){throw 'stderr wrongly terminated successful stage'}
    if([int]$stageRecords['SECTORS'].exit_code -ne 0){throw 'successful child exit code lost'}
    $log=[IO.File]::ReadAllText([string]$stageRecords['SECTORS'].log_path)
    if(-not $log.Contains('QMT_CACHE_WORKER_UTF8_DECODE_ERROR') -or
       -not $log.Contains('MARKET_QMT_EXTRA_SUMMARY=')){
        throw 'stderr or structured JSON was not captured'
    }
    $failed=Join-Path $temp 'failed.ps1'
    [IO.File]::WriteAllText($failed,@'
[Console]::Error.WriteLine("----------------------------------------------------------------------")
Write-Output "MOCK_NONZERO"
exit 85
'@)
    Invoke-MarketStage -Label 'FINANCIAL_DAILY' -Script $failed -Arguments @()
    if($completed.Count -ne 1 -or $failures.Count -ne 1){throw 'nonzero native exit was not recorded as failure'}
    if([int]$stageRecords['FINANCIAL_DAILY'].exit_code -ne 85){throw 'nonzero exit code lost'}
    Write-Host 'PASS_NATIVE_STDERR_NONTERMINATING_AND_NONZERO_GUARDED_NO_REAL_DATA'
}finally{
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
