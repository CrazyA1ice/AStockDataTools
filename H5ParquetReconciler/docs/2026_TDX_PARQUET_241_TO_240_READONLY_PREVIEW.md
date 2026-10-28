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
