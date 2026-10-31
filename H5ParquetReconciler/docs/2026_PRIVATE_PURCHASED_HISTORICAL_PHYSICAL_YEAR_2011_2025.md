# 第二十阶段：2011—2025购买Parquet私有物理年，2016仅补一条已审H5候选

## 上一阶段真实结果
2026年物理年度数据已于Windows真实物化和独立验收：1,032,623根（购买1,010,350、H5整日22,191、H5混合82），10个私有物理Parquet分区的SHA、逐行Float64往返和SQLite股票日唯一键检验PASS。已有源SAFE `reports/physical-2026-purchased-plus-h5-f6d4a6e87887.json` 和独立审计SAFE `reports/physical-2026-independent-full-audit-318b43aa9daf.json`。不再重建2026年。

## 实施方式
新增`tools/materialize-private-2011-2025-purchased-year.py`：`--year`一次只能是2011..2025中的一个年份。严格验证原始 QDC `【先看我】数据说明.txt` 与 `文件校验清单.txt` 两个原件PIN SHA，严格解析包含全24文件的随包清单，并对本年 `day/<year>.parquet` 原始文件执行大小、整文件SHA256及Footer行数预检。只复制本年原始日线，不缩放不取整；保留原原始证券编码source_symbol、标准代码symbol和Float64，逐行写入完全独立的`work/unified_parquet/physical_years/physical_<year>_<hex>`，生成SQLite全球唯一股票日约束。每分区源端Float64原始字节行SHA和重读后完全一致，出错即fail closed。
**2016年特殊路径**：在读取原购买年度文件之前，对已验的22,274条H5候选再跑一次完整安全审计，只从其2016分区导入**恰好1条**`private_h5_mixed_stockday_candidate`。购买/候选任一重复股票日键拒绝成功SAFE。其他14个年份H5候选应为0，不强制重复全22,274行H5审计，不会把H5当购买。
新增`tools/verify-private-2011-2025-purchased-year.py`：**独立逐行**检查新私有年度输出、每分区SHA、schema、原始Float64行SHA、规范股票日键和SQLite对应关系。该独立校验器不重新打开原始QDC/H5，不能替代源新鲜度审计和供应商真实性认证。

## 绝对保持的安全边界
- 原始购买Parquet、Hikyuu H5、生产路由和私有active pointer都不得写入；新版年度Parquet、SQLite和任何未通过的工作残留只放`H5ParquetReconciler/work/`；脱敏SAFE只放模块`reports/`。严禁上传私有市场数据和真实股票代码清单。
- 原购买单位以收到的vendor README声明为证据，不把该文件当独立发行真实性证明。H5金额舍入/复权、2011年前H5历史与证券代码身份尚未全部认证，`candidate_source_units_certified=false`、`ready_for_automatic_market_merge=false`、`ready_for_h5_mirror=false`。
- 各年份SAFE独立，2011..2025全验收后才建立跨年统一版本与不可变总manifest，不自动切换原本2026已验收版。旧市场数据历史是否完整需验证文件自身记录，不能臆造缺失日期。2026年7月16日5条H5异常候选继续隔离。

## Windows步骤一：48项合成与回归测试（每行一条命令）
```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "历史年分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\materialize-private-2011-2025-purchased-year.py H5ParquetReconciler\tools\verify-private-2011-2025-purchased-year.py H5ParquetReconciler\tests\test_private_2011_2025_purchased_physical_year.py; if ($LASTEXITCODE -ne 0) { throw "新增历史年代码语法失败" }; $patterns=@("test_private_2011_2025_purchased_physical_year.py","test_private_2026_purchased_h5_physical_year.py","test_materialize_private_full_22274_gap_candidates.py","test_query_private_purchased_plus_22274_candidates.py"); foreach ($p in $patterns) { .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p $p -v; if ($LASTEXITCODE -ne 0) { throw "历史年或已验2026回归失败：$p；禁止真实物化" } }; Write-Host "PASS：新增10项历史年+2026年10项+H5候选11项+私有查询17项，共48项"
```

## Windows步骤二：先真实物化2016年单年份（成功前不要运行其余14年）
```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $dir="H5ParquetReconciler\work\unified_parquet\physical_years\physical_2016_$rid"; $gate="H5ParquetReconciler\reports\historical-2016-h5-full-source-gate-$rid.json"; $out="H5ParquetReconciler\reports\historical-physical-2016-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\materialize-private-2011-2025-purchased-year.py --year 2016 --purchased-root "D:\stock\AllCycleAStockData" --candidate-safe "H5ParquetReconciler\reports\full-22274-private-candidates-60ae77774c30.json" --readme-sha256 "4c4e7c2081390407a06fecbe8b2693bddc9ce76191c44381b6be0e7781a2f023" --manifest-sha256 "24f099faeb0a2e810f46691b81b2a357cc5aa42cd7ccd800dae6e19db16b06eb" --private-year-dir $dir --candidate-verification-out $gate --out $out --private-historical-year-only; if ($LASTEXITCODE -ne 0) { throw "2016年历史购买+1条H5缺口私有物化失败；不得启动生产或复用未验work目录" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; $pc=@($r.physical_partition_sha256.PSObject.Properties.Name).Count; if ($r.year -ne 2016 -or $r.status -ne "private_purchased_historical_day_physical_year_not_activated" -or $r.purchased_original_rows -lt 1 -or $r.h5_mixed_candidate_rows -ne 1 -or $r.total_private_physical_rows -ne ($r.purchased_original_rows+1) -or $pc -ne 2 -or $r.original_float64_roundtrip_exact -ne $true -or $r.original_market_files_written -ne $false -or $r.original_purchased_parquet_replaced -ne $false -or $r.private_or_production_active_pointer_modified -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.ready_for_h5_mirror -ne $false) { throw "2016年原始购买+H5候选私有物化报告校验失败" }; Write-Host "PASS：2016私有购买$($r.purchased_original_rows)条 + 审核H5混合候选1条，原源未修改"; Write-Host "SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

## Windows步骤三：2016物理年度独立逐行验收
```powershell
cd D:\ChatGPT\AStockDataTools; $s=Get-ChildItem "H5ParquetReconciler\reports\historical-physical-2016-*.json" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($null -eq $s) { throw "没有2016真实成功物化SAFE" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\historical-physical-2016-independent-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\verify-private-2011-2025-purchased-year.py --materialization-safe $s.FullName --out $out --verify-private-only; if ($LASTEXITCODE -ne 0) { throw "2016全行SHA/Float64/股票日键独立审计失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "independent_historical_private_physical_year_all_rows_sha_and_keys_verified" -or $r.year -ne 2016 -or $r.private_purchased_rows_verified -lt 1 -or $r.private_h5_mixed_candidate_rows_verified -ne 1 -or $r.private_total_rows_verified -ne ($r.private_purchased_rows_verified+1) -or $r.private_partition_files_verified -ne 2 -or $r.original_float64_roundtrip_fingerprint_verified -ne $true -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.ready_for_h5_mirror -ne $false -or $r.original_market_files_written -ne $false) { throw "2016独立验收SAFE不符合预期" }; Write-Host "PASS：2016购买全年+1条H5混合缺口独立全量核验成功"; Write-Host "SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

通过后下一轮再一次性推出2011..2015及2017..2025共14个年份的批处理命令，生成逐年份独立SAFE，最后将2011—2026年的16个已验收年度绑定到同一个**未激活的**跨年私有manifest和版本回滚机制。

## 2026-10-31 Windows真实2016试运行失败后：只读诊断（**先于任何重试**）

此前2016原始购买Parquet+1条H5候选真实物化被现有CLI拦截，仅返回`Historical purchased DAY annual private physical materialization refused`。该字符串是旧入口对多类异常的统一提示，**不能据此断言哪一个输入值有问题**。可能有全量来源gate SAFE或未发布的私有工作目录，**不得删除、覆盖或启用**。2026年的1,032,623条物理年度数据已经独立验收通过，不需要重做。

新增`tools/diagnose-private-2016-purchased-h5-readonly.py`：不建立年度Parquet/SQLite、不触碰原始源，核对原2016购买年度文件整文件SHA、Footer和每行的源时间戳/代码/Float64/OHLC结构，再与SHA固定的2016唯一H5候选核对复合股票日唯一键。失败时用**固定英文原因代码**和阶段（如`purchased_rows`、`h5_candidate`）写一个新脱敏SAFE，绝不输出股票名、代码、日期、原始路径、OHLCVA或底层异常全文。诊断成功仅表示静态来源字段与主键自洽，不认证vendor金额舍入、全市场缺口新鲜度，也不能取代物理年度独立验证。新增4项合成测试，历史年测试累计14项。

**A. 先拉取诊断分支并跑14项安全测试（单行PowerShell）：**

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换历史物理年分支失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\diagnose-private-2016-purchased-h5-readonly.py H5ParquetReconciler\tests\test_private_2011_2025_purchased_physical_year.py; if ($LASTEXITCODE -ne 0) { throw "安全诊断代码语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_private_2011_2025_purchased_physical_year.py" -v; if ($LASTEXITCODE -ne 0) { throw "2016历史年14项安全测试失败，禁止真实物化" }; Write-Host "PASS：14项历史年度物化和只读诊断合成测试全部通过"
```

**B. 只读列举之前失败后的目录与验证SAFE状态（不导出行情）：**

```powershell
cd D:\ChatGPT\AStockDataTools; Write-Host "2016年未激活工作目录（仅名称与文件数量）"; Get-ChildItem "H5ParquetReconciler\work\unified_parquet\physical_years" -Directory -Filter "physical_2016_*" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name,LastWriteTime,@{Name="parquet_files";Expression={@(Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Filter "*.parquet" -ErrorAction SilentlyContinue).Count}},@{Name="has_manifest";Expression={Test-Path -LiteralPath (Join-Path $_.FullName "manifest.json")}} | Format-Table -AutoSize; Write-Host "最近2016年候选全量审计SAFE（只看文件名）"; Get-ChildItem "H5ParquetReconciler\reports" -File -Filter "historical-2016-h5-full-source-gate-*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name,Length,LastWriteTime | Format-Table -AutoSize
```

**C. 在14项通过后，运行2016年独立只读诊断（不重建大文件）：**

```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\historical-2016-readonly-diagnostic-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\diagnose-private-2016-purchased-h5-readonly.py --purchased-root "D:\stock\AllCycleAStockData" --candidate-safe "H5ParquetReconciler\reports\full-22274-private-candidates-60ae77774c30.json" --readme-sha256 "4c4e7c2081390407a06fecbe8b2693bddc9ce76191c44381b6be0e7781a2f023" --manifest-sha256 "24f099faeb0a2e810f46691b81b2a357cc5aa42cd7ccd800dae6e19db16b06eb" --out $out --diagnose-2016-readonly; $exit=$LASTEXITCODE; if (-not (Test-Path -LiteralPath $out)) { throw "诊断未生成SAFE，退出码=$exit；停止后续物化" }; $d=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($d.original_market_files_written -ne $false -or $d.private_annual_parquet_or_sqlite_created -ne $false -or $d.ready_for_automatic_market_merge -ne $false) { throw "诊断报告违反只读安全边界" }; Write-Host "诊断退出码=$exit；状态=$($d.status)；失败阶段=$($d.failure_stage)；失败原因代码=$($d.failure_code)"; Write-Host "已检查购买原始行数=$($d.purchased_rows_checked_before_refusal)；H5候选行数=$($d.h5_candidate_rows_checked_before_refusal)"; Write-Host "诊断SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

诊断程序若拒绝返回退出码2属**预期可分析结果**，不要立即重复物化。回传`reports/historical-2016-readonly-diagnostic-*.json`的脱敏内容与单元测试日志。若状态`readonly_2016_historical_preflight_pass`但旧物化仍拒绝，问题发生在物理Parquet或SQLite写读/manifest发布阶段，应基于上一步的工作目录状态进一步修正代码，仍不覆盖旧文件。物化原始数据与2016单股代码清单不要上传GitHub。
