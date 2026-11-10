# Synthetic Windows PowerShell 5.1 regression for empty H5 provenance maps.
# No market data, no filesystem changes outside the test process.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent (Split-Path -Parent $PSCommandPath)
. (Join-Path $module 'verify-catalog-bound-eight-cycle-sources.ps1')
function Assert-Counts {
    param([string]$Json,[bool]$AllowPrivate,[long]$ExpectedPurchased,[long]$ExpectedPrivate)
    $item=$Json|ConvertFrom-Json
    $v=Get-CatalogBoundEightCycleSourceCounts -PeriodSummary $item -AllowPrivate $AllowPrivate
    if($v.Purchased -ne $ExpectedPurchased -or $v.Private -ne $ExpectedPrivate -or $v.Total -ne ($ExpectedPurchased+$ExpectedPrivate)){
        throw ('Unexpected synthetic provenance: '+$Json)
    }
}
function Assert-Rejected {
    param([string]$Json,[bool]$AllowPrivate)
    $item=$Json|ConvertFrom-Json
    $rejected=$false
    try {$null=Get-CatalogBoundEightCycleSourceCounts -PeriodSummary $item -AllowPrivate $AllowPrivate}
    catch {$rejected=$true}
    if(-not $rejected){throw ('Unsafe source count accepted: '+$Json)}
}
# Cases 1..3: originally failed on empty/nonexistent H5 entries.
Assert-Counts '{"period":"day","matching_bar_count":1,"bars_by_source":{"purchased_parquet":1}}' $false 1 0
Assert-Counts '{"period":"week","matching_bar_count":0,"bars_by_source":{}}' $false 0 0
Assert-Counts '{"period":"month","matching_bar_count":0,"bars_by_source":{"purchased_parquet":0}}' $false 0 0
# Cases 4..5: previously passed source priority must stay exact.
Assert-Counts '{"period":"1min","matching_bar_count":1201,"bars_by_source":{"purchased_parquet":241,"verified_private_h5_gap":960}}' $true 241 960
Assert-Counts '{"period":"15min","matching_bar_count":80,"bars_by_source":{"purchased_parquet":16,"research_derived_candidate_from_sha_verified_h5_5min":64}}' $true 16 64
# Cases 6..9: private day/week/month, mismatched sums and invalid values fail closed.
Assert-Rejected '{"period":"day","matching_bar_count":2,"bars_by_source":{"purchased_parquet":1,"unexpected_h5_candidate":1}}' $false
Assert-Rejected '{"period":"week","matching_bar_count":5,"bars_by_source":{"purchased_parquet":4}}' $false
Assert-Rejected '{"period":"month","matching_bar_count":0,"bars_by_source":{"purchased_parquet":-1}}' $false
Assert-Rejected '{"period":"day","matching_bar_count":1,"bars_by_source":{"purchased_parquet":"1"}}' $false
Write-Host 'PASS_CATALOG_BOUND_EIGHT_CYCLE_POWERSHELL_EMPTY_H5_SOURCE_TESTS TESTS=9 ORIGINAL_MARKET_WRITES=FALSE'
