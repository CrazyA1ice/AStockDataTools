# Offline-only P9 disclosure-vintage and Unicode proof (NO QMT, NO ledger read).
# P8 historical HOLD proof + 002328 early/late disclosure; never a recovery writer.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepoRoot,
      [Parameter(Mandatory=$true)][string]$ReviewCommit)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$expectedProductionHead='2b5c1bd28f8df4d4512dd933e50b1be50741f6a6'
$python=Join-Path $RepoRoot '.venv\Scripts\python.exe'
$files=@(
@{Path='ParquetLiveSync/finance_five_review_freeze_once.py';Blob='20932f82d972441ec16379939d841d5447e24af0'}
@{Path='ParquetLiveSync/finance_five_adjudication_dossier_once.py';Blob='902f94a034864fb597e6a67f27a5a7e5fb96c719'}
@{Path='ParquetLiveSync/finance_public_source_crosscheck_once.py';Blob='d938bbbb5eeba31c432c8f46a75e614eb890face'}
@{Path='ParquetLiveSync/finance_disclosure_vintage_provenance_once.py';Blob='84cec2b62576c86d562717a654a7c8f3e18bf867'}
@{Path='ParquetLiveSync/tests/test_finance_disclosure_vintage_provenance_once.py';Blob='bdbb1bdc4981776c55a6bc9cc3eb04e6f6cdabfb'}
@{Path='ParquetLiveSync/docs/finance-five-review-freeze-20261125.json';Blob='31b1bec53afae2598ab2e09d1d18f9bb984ae63e'}
@{Path='ParquetLiveSync/docs/finance-five-pilot-review-evidence-20261125.json';Blob='5a39ec2777cde87b686146156ca7f56fdf4b1374'}
@{Path='ParquetLiveSync/docs/finance-priority-three-adjudication-manifest-20261125.json';Blob='3ba609a9b9200ee18093104fb29dd205acaecd68'}
@{Path='ParquetLiveSync/docs/finance-002188-top10holder-raw-multiplicity-pin-20261125.json';Blob='b9f4aeab54b46ea652711455e770c7046dec6a2e'}
@{Path='ParquetLiveSync/docs/finance-five-adjudication-dossiers-20261125.json';Blob='d077dddce7f8fefdf2b6e8fb67f01b54d9328c5b'}
@{Path='ParquetLiveSync/docs/finance-public-source-crosscheck-20261125.json';Blob='ebd73d00468fb5c20afa0749c9e56cf6b7e2f2dc'}
@{Path='ParquetLiveSync/docs/finance-disclosure-vintage-codepoint-20261125.json';Blob='5d830a75c1471205d6d3273faf5c36eec02cb2d7'}
)
if($ReviewCommit -notmatch '^[0-9a-f]{40}$'){throw 'REVIEW_COMMIT_PIN_FORMAT_INVALID'}
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'LOCAL_VENV_MISSING'}
$actualHead=git -C $RepoRoot rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $actualHead.Trim() -ne $expectedProductionHead){throw 'CANONICAL_PRODUCTION_GIT_HEAD_CHANGED_STOP'}
$actualReview=git -C $RepoRoot rev-parse $ReviewCommit
if($LASTEXITCODE -ne 0 -or $actualReview.Trim() -ne $ReviewCommit){throw 'PINNED_REVIEW_COMMIT_UNAVAILABLE'}
$gitexe=(Get-Command git -ErrorAction Stop).Source
$stage=Join-Path $env:TEMP ('finance-disclosure-vintage-'+[guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path (Join-Path $stage 'ParquetLiveSync\docs') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stage 'ParquetLiveSync\tests') -Force | Out-Null
    foreach($file in $files){
        $spec=$ReviewCommit+':'+$file.Path
        $found=git -C $RepoRoot rev-parse $spec
        if($LASTEXITCODE -ne 0 -or $found.Trim() -ne $file.Blob){throw "REVIEW_BLOB_PIN_CHANGED=$spec"}
        $destination=Join-Path $stage $file.Path.Replace('/','\')
        $psi=New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName=$gitexe
        $psi.Arguments='cat-file blob '+$found.Trim()
        $psi.WorkingDirectory=$RepoRoot
        $psi.UseShellExecute=$false
        $psi.RedirectStandardOutput=$true
        $psi.RedirectStandardError=$true
        $p=[System.Diagnostics.Process]::Start($psi)
        try {
            $stream=[System.IO.File]::Open($destination,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
            try{$p.StandardOutput.BaseStream.CopyTo($stream)}finally{$stream.Dispose()}
            $errorText=$p.StandardError.ReadToEnd()
            $p.WaitForExit()
            if($p.ExitCode -ne 0){throw "REVIEW_STAGE_GIT_FAILED=$spec $errorText"}
        } finally {$p.Dispose()}
        $verified=git -C $RepoRoot hash-object -- $destination
        if($LASTEXITCODE -ne 0 -or $verified.Trim() -ne $file.Blob){throw "REVIEW_STAGED_BLOB_BAD=$spec"}
    }
    $base=Join-Path $stage 'ParquetLiveSync'
    Write-Host '===FINANCE_VINTAGE_PROVENANCE_OFFLINE_TESTS_38==='
    & $python -B (Join-Path $base 'tests\test_finance_disclosure_vintage_provenance_once.py') -q
    if($LASTEXITCODE -ne 0){throw 'VINTAGE_PROVENANCE_38_OFFLINE_TESTS_FAILED'}
    Write-Host 'FINANCE_VINTAGE_PROVENANCE_38_TESTS_PASS'
    Write-Host '===FINANCE_VINTAGE_PROVENANCE_HOLD_ONLY_NO_QMT==='
    & $python -B (Join-Path $base 'finance_disclosure_vintage_provenance_once.py') --directory (Join-Path $base 'docs')
    if($LASTEXITCODE -ne 0){throw 'FINANCE_VINTAGE_PROVENANCE_VALIDATION_FAILED'}
    Write-Host 'FINANCE_VINTAGE_PROVENANCE_PASS_NO_QMT_NO_APPROVAL'
} finally {
    if(Test-Path -LiteralPath $stage){Remove-Item -LiteralPath $stage -Force -Recurse -ErrorAction SilentlyContinue}
}
Write-Host 'FINANCE_VINTAGE_PROVENANCE_COMPLETE_NO_DEPLOY'
