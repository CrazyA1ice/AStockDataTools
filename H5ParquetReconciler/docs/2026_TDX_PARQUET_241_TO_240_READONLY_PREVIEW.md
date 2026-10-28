# 2026-10-28：Parquet 241分钟→TDX 240分钟候选视图只读预演

## 真实证据范围与限制

用户已回传安全汇总 tdx-pq-opening-cohort-ten-stockdays.json：
10组独立股票日，4只股票、4个日期，全部10/10
开盘合并、其余239根、重建240根及原购买48根五分钟均通过。
股票包括SH600000、SZ000001、SH600519和SZ300750；日期包括
2026-08-17、2026-09-28、2026-09-29、2026-09-30。
这不等于全市场转换认证；Parquet来源仅有stat-only清单指纹。

## 新工具

tools/preview-tdx-parquet-1min-normalization-readonly.py

只读输入：目标股票日的一份原生TDX .lc1和购买Parquet的1min及5min。
必须严格核验TDX完整文件SHA以及日期240 END标签；购买Parquet
1min完整241（单独09:30）及5min完整48 START标签；不得出现缺失、
重复、非有限价格或负成交量。Parquet源查询使用候选行数限制，禁用缓存。

内存中构建候选241→240：第一根取购买Parquet09:30和09:31的
开盘第一条、最高最大、最低最小、收盘最后一条、量额求和，
所得新记录的END标签为09:31；剩余239根来源记录直接对齐保留。
不丢弃或写入任何原始记录；所有241条原始输入恰好参与一次候选计算。
候选只在Python内存中存在，不输出逐笔行情或具体时间标签。

独立四道六字段容差门槛：
1) 首根候选 vs TDX首根（1根）；
2) 剩余239根候选 vs TDX对应239根；
3) 完整候选240根 vs TDX原生240根；
4) 候选240根按5条聚合为48根 vs 购买Parquet原生5min。
任意字段不匹配，则输出diagnostic_candidate_mismatch_do_not_materialize；
全部通过，则是diagnostic_candidate_matches_both_sources_not_production_certified。
两个分支均不持久化240根数据、不修改任何TDX/Parquet/H5文件，
不写私有缓存、暂存、生产查询和自动并集。安全JSON只有字段级
匹配数、误差、来源指纹与贡献行数说明，没有真实价量额。

## 2026-10-28真实首次预演验收（用户本机实际回传）

文件：tdx-pq-sh600000-20260930-normalization-preview-v1.json
真实股票日：SH600000 / 2026-09-30。
用户已在Windows运行241→240只读候选程序并回传完整安全JSON，
不是单纯由之前的摘要推导。关键结论：

- 原始Parquet分钟241根，内存候选240根；第一根聚合使用原始2条，
  其余239条各自使用1条；原始241条全部参与、没有删除或新造分钟。
- 候选首根vs TDX首根：六字段1/1匹配；其余239根：六字段239/239匹配；
  完整候选240根：六字段240/240匹配；候选聚合到购买5min：六字段48/48匹配。
- 完整240根比较中四个价格字段最大相对差均不超过4.96e-08，
  volume和amount最大相对误差均为0。
- gates.diagnostic_preview_consistent=true，preview_verdict=
  diagnostic_candidate_matches_both_sources_not_production_certified。
- candidate_ohlcva_exported=false、original_sources_modified=false、
  private_staging_or_production_union_performed=false、
  eligible_for_automatic_production_union=false；
  Parquet仍然只有stat-only来源指纹，尚不具备内容认证。

这是**一个股票日的候选转换实际验收**；之前10个股票日是
假说/原始分钟核验，尚未全部运行此新候选预演工具。
新增8项合成测试的Windows执行结果也尚未收到，不能宣称已通过。

## 下一轮：对其余9个已知源股票日批量运行候选预演

已通过的SH600000/2026-09-30不要重复执行；以下命令会核验
其余九组来源文件和输出新文件名是否可用，成功则保留各自安全JSON。
任何脚本错误都停止后续运行，不会补造/修改任何市场记录。

PowerShell单行命令（在 D:\ChatGPT\AStockDataTools 仓库根目录执行）：

```powershell
$cases=@(@("SH600000","2026-09-28"),@("SH600000","2026-09-29"),@("SZ000001","2026-09-28"),@("SZ000001","2026-09-29"),@("SZ000001","2026-09-30"),@("SH600519","2026-08-17"),@("SH600519","2026-09-30"),@("SZ300750","2026-08-17"),@("SZ300750","2026-09-30")); foreach($c in $cases){$symbol=$c[0];$day=$c[1];$market=$symbol.Substring(0,2).ToLower();$src="D:\software\TDX\vipdoc\$market\minline\$($symbol.ToLower()).lc1";$out="reports\tdx-pq-$($symbol.ToLower())-$($day.Replace('-',''))-normalization-preview-v1.json";if(!(Test-Path $src)){Write-Warning "源文件不存在：$src";break};if(Test-Path "H5ParquetReconciler\$out"){Write-Warning "输出已存在，拒绝覆盖：$out";break};& ".\.venv\Scripts\python.exe" "H5ParquetReconciler\tools\preview-tdx-parquet-1min-normalization-readonly.py" --parquet-root "D:\stock" --tdx-1min-file $src --symbol $symbol --date $day --read-only --out $out;if($LASTEXITCODE -ne 0){Write-Warning "预演失败：$symbol $day";break}}
```

请同时单独执行之前文档列出的8项合成测试，并保留真实报错。
优先分析首个失败股票日，不应为了凑齐成功报告修改原始价量额。

## Windows验收：均为单行PowerShell

在 D:\ChatGPT\AStockDataTools 根目录执行：

git pull --ff-only origin main

先检查语法与合成测试（8项，尚需Windows真实执行）：

.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\preview-tdx-parquet-1min-normalization-readonly.py; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_preview_tdx_parquet_1min_normalization_readonly.py" -v

使用已知通过的SH600000/2026-09-30做首次真实只读预演：

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\preview-tdx-parquet-1min-normalization-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-30 --read-only --out "reports\tdx-pq-sh600000-20260930-normalization-preview-v1.json"

输出必须为新的 H5ParquetReconciler/reports/*.json，拒绝覆盖已存在的文件。

后续需要更多历史月份、停复牌、复权等异常样本进行边界核验。
生产映射和私有版本暂存必须由用户另行显式授权。
