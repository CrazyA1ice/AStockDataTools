param(
  [int]$MaxHosts = 6,
  [int]$MaxPages = 16
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$b = "feat/qmt-one-minute-history-probe-20261112"
if ((& git branch --show-current).Trim() -ne $b) {throw "Wrong QMT source branch"}
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {throw "Repository Python missing"}
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "ELTDX_STEP_1_OFFLINE_TEST_AND_NATIVE_RUST_WHEEL"
& $py -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt_eltdx_1m_probe.py" -q
if ($LASTEXITCODE -ne 0) {throw "ELTDX offline tests failed; no live source queried"}
& $py -c "import eltdx; print('ELTDX_VERSION='+str(eltdx.__version__))"
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing official eltdx prebuilt wheel into this venv (not compiling arbitrary Rust)"
  & $py -m pip install --only-binary=:all: "eltdx" -i https://pypi.org/simple
  if ($LASTEXITCODE -ne 0) {
    & $py -m pip install --only-binary=:all: "eltdx" -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -ne 0) {throw "ELTDX official wheel unavailable, use TDX offline downloads"}
  }
}
Write-Host "ELTDX_STEP_2_REAL_1MIN_22_DAY_SH_SZ_STAR_PILOT"
$logs=Join-Path $PSScriptRoot "work\qmt_1min_market\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$prefix=Join-Path $logs ("eltdx-full-1m-"+(Get-Date -Format "yyyyMMdd-HHmmss"))
$out=$prefix+".stdout.log"
$err=$prefix+".stderr.log"
# Start-Process rather than native pipe avoids Windows PowerShell 5.1
# treating any Python stderr warning as a terminating NativeCommandError.
$task=Start-Process -FilePath $py -ArgumentList @("-u","-B","ParquetLiveSync\qmt_eltdx_1m_probe.py","--max-hosts",$MaxHosts,"--max-pages",$MaxPages) -NoNewWindow -PassThru -Wait -RedirectStandardOutput $out -RedirectStandardError $err
Get-Content -LiteralPath $out -Encoding UTF8 | Where-Object {$_ -match "^ELTDX_"} | ForEach-Object { Write-Host $_ }
if ((Get-Item $err).Length -gt 0) {
  Write-Host "ELTDX_DIAGNOSTICS_STDERR_LAST_LINES"
  Get-Content -LiteralPath $err -Tail 8
}
Write-Host ("ELTDX_TEST_LOG="+$out)
Write-Host ("ELTDX_REAL_PROBE_EXIT_CODE="+$task.ExitCode)
if ($task.ExitCode -eq 0) {
  Write-Host "ELTDX_REAL_ONE_MINUTE_SOURCE_AVAILABLE_REVIEW_QMT_DIFFERENCES"
} else {
  Write-Host "ELTDX_REAL_ONE_MINUTE_SOURCE_UNAVAILABLE_OR_INCOMPLETE"
  Write-Host "NEXT_INPUT_IF_NEEDED=Tongdaxin after-hours downloaded original 1-minute files"
}
Write-Host "PRODUCTION_PARQUET_AND_H5_UNCHANGED"
