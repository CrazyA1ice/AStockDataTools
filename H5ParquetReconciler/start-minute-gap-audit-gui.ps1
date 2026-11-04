# Open the safe source-key-only minute audit GUI. Never starts legacy writer.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$py=Join-Path $repo '.venv\Scripts\python.exe'
$pyw=Join-Path $repo '.venv\Scripts\pythonw.exe'
$gui=Join-Path $module 'tools\minute-gap-audit-gui.py'
if(-not (Test-Path -LiteralPath $py -PathType Leaf)){throw "Project Python venv missing: $py"}
if(-not (Test-Path -LiteralPath $gui -PathType Leaf)){throw "Safe minute audit GUI missing: $gui"}
$tests=@('test_preview_minute_exact_key_diff_readonly.py','test_build_minute_purchased_key_index.py','test_audit_minute_index_window_readonly.py','test_ensure_minute_key_index_window.py','test_minute_gap_audit_gui_worker.py')
foreach($p in $tests){
    & $py -B -m unittest discover -s (Join-Path $module 'tests') -p $p -q
    if($LASTEXITCODE -ne 0){throw "GUI backend safety regression FAILED: $p. Interface was not launched."}
}
if(-not (Test-Path -LiteralPath $pyw -PathType Leaf)){$pyw=$py}
Write-Host '安全验收测试通过。正在打开分钟数据只读核对控制台……'
$process=Start-Process -FilePath $pyw -ArgumentList ('"'+$gui+'"') -WorkingDirectory $module -PassThru
Write-Host "GUI进程PID=$($process.Id)；原购买Parquet与H5不会被GUI或其核对worker写入。"
