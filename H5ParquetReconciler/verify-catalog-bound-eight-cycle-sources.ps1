# Read-only JSON source-count helper for Windows PowerShell 5.1.
# No file access, no market reads, no writes. 'Other' count may be zero:
# day/week/month routinely have no private H5 source entries.
function Get-CatalogBoundEightCycleSourceCounts {
    param(
        [Parameter(Mandatory=$true)]$PeriodSummary,
        [bool]$AllowPrivate = $false
    )
    if($null -eq $PeriodSummary -or $null -eq $PeriodSummary.bars_by_source){
        throw 'Missing source-count map in eight-cycle SAFE summary'
    }
    $count=$PeriodSummary.matching_bar_count
    if(($count -isnot [int] -and $count -isnot [long]) -or $count -lt 0){
        throw 'Invalid matching_bar_count in eight-cycle SAFE summary'
    }
    $purchased=[long]0
    $private=[long]0
    $seenPaid=$false
    $props=@($PeriodSummary.bars_by_source.PSObject.Properties)
    if($props.Count -gt 32){throw 'Too many provenance source categories'}
    foreach($entry in $props){
        $value=$entry.Value
        if(($value -isnot [int] -and $value -isnot [long]) -or $value -lt 0){
            throw ('Invalid numeric source count: '+$entry.Name)
        }
        if($entry.Name -eq 'purchased_parquet'){
            if($seenPaid){throw 'Duplicate purchased provenance source'}
            $seenPaid=$true
            $purchased=[long]$value
        }else{
            $private += [long]$value
        }
    }
    if($private -gt 0 -and -not $AllowPrivate){
        throw 'Unregistered day/week/month source has private/H5 candidate bars'
    }
    if($purchased+$private -ne [long]$count){
        throw 'Period source counts do not conserve matching bars'
    }
    return [pscustomobject]@{
        Purchased=$purchased
        Private=$private
        Total=[long]$count
        HasPurchasedSource=$seenPaid
    }
}
