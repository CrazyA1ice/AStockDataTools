# 2026-11-01 日线已写出后：1min/5min真实H5完整股票日→私有Parquet补缺

已完成：2011—2026年Parquet私有日线14,137,981条已经写到三市场原生40字节Hikyuu H5并全部整数回读；SAFE `reports/full-2011-2026-native-h5-day-3dc5044a4122.json`。成交额14,089,850条发生整数舍入变化、最大500；OHLC各6条最大约0.000258；这**不是Parquet Float64与H5绝对无损同步**。已有8条真实证券日验证Hikyuu 2.8.1 C++可读，全市场H5 C++尚未验证。**不要重新生成日线。**

本轮按用户要求直接写出1分钟及5分钟实际私有Parquet新增分区，不再建立索引/性能测试。

新增 `tools/write-h5-only-complete-minute-stockdays-to-private-parquet.py`：对2025/2026年指定交易日，各周期读原购买Parquet仅`ts/symbol`两列，按**股票+交易日**判断是否有购买行；若已有哪怕1条购买分钟线，该股票日全部由购买Parquet保持优先，不用H5覆盖；若完全没有，从真实`D:\stock\HikyuuData\{sh,sz,bj}_{period}.h5`提取该完整股票日。5min必须恰好48条且符合09:35—11:30、13:05—15:00终点网格；1min允许239/240条且符合09:31—11:30、13:01—15:00终点网格；其余不写入、只统计隔离原因。仅以H5终点减5或1分钟**候选映射**写Parquet的`ts`，明示该映射尚未完成厂商语义认证，不能直接并入正式统一库。

新文件为`work/unified_parquet/minute_gap_staging/<runid>/1min/2026-10-13.parquet`和`.../5min/2026-10-13.parquet`（每次新runid）；包含`ts,symbol,open/high/low/close,volume,amount,h5_native_datetime,h5_native_{six raw integer},value_source,period`，既保存转换值也保存H5原始整数，避免未来反向H5镜像时丢失源值。每32,768条一批写Parquet，**不会把全市场一分钟数据累计成百万行Python字典**；写完全行整数和OHLCVA重新读取比对SHA。原购买Parquet和原H5完全只读，任何异常都不发布成功SAFE。若BJ分钟源不存在，按缺失市场在报告中明确记录，不阻塞已有SH/SZ实际补缺。

2项简短合成集成测试：1min 240条+5min 48条真实H5→私有Parquet，且存在购买记录的证券日不混入；不完整的5min交易日被隔离。**尚未收到本机2026-10-13真实分钟补缺运行结果，不宣称生产合并或两库分钟线已一致。**

## 立即在Windows执行（PowerShell单行）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\write-h5-only-complete-minute-stockdays-to-private-parquet.py H5ParquetReconciler\tests\test_write_h5_only_complete_minute_stockdays_to_private_parquet.py; if ($LASTEXITCODE -ne 0) { throw "1min/5min写出工具语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_write_h5_only_complete_minute_stockdays_to_private_parquet.py" -v; if ($LASTEXITCODE -ne 0) { throw "两项分钟私有Parquet实际写盘测试失败，禁止读取真实H5" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\real-minute-h5-only-private-parquet-20261013-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\write-h5-only-complete-minute-stockdays-to-private-parquet.py --root "D:\stock" --day 2026-10-13 --run-id $rid --max-purchased-key-rows 30000000 --max-h5-rows 2500000 --out $out --write-private-minute-gaps-only; if ($LASTEXITCODE -ne 0) { throw "真实1min/5min H5补Parquet写出失败；原购买Parquet/H5均未修改" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.original_market_files_modified -ne $false -or $r.all_private_outputs_written_not_merged -ne $true -or $r.period_results.'1min'.status -ne "h5_complete_stockday_minute_gap_private_parquet_written_readback_not_merged" -or $r.period_results.'5min'.status -ne "h5_complete_stockday_minute_gap_private_parquet_written_readback_not_merged" -or $r.period_results.'1min'.source_purchased_parquet_stockdays_priority_preserved -ne $true -or $r.period_results.'5min'.source_purchased_parquet_stockdays_priority_preserved -ne $true) { throw "分钟补缺SAFE验收失败" }; Write-Host "PASS：两周期H5完整股票日缺口已生成隔离Parquet，原始数据不变"; Write-Host "1min补缺行：$($r.period_results.'1min'.private_parquet_rows)，股票日：$($r.period_results.'1min'.private_parquet_stockdays)"; Write-Host "5min补缺行：$($r.period_results.'5min'.private_parquet_rows)，股票日：$($r.period_results.'5min'.private_parquet_stockdays)"; Write-Host "候选时间口径尚未正式认证、未自动合并"; Write-Host "SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

如果数据范围不在2026-10-13，可把`--day`换成已有H5的实际交易日；仍保持1分钟和5分钟成对写入。执行后查看脱敏SAFE中的两个`private_parquet_rows`、购买已有股票日数、H5隔离原因和文件SHA。下一步把这些**实际落盘的私有分钟增量**与购买Parquet并成新的规范分钟分区，再基于统一分钟Parquet生成独立原生Hikyuu `sh_1min.h5`/`sh_5min.h5`等，回读比对并为TDX增量准备，不重做日线。

**注意：** 仅把H5独有的完整股票日补到新Parquet；对已有购买股票日内部缺少的分钟条目目前不会静默补写，后续在保持购买优先和时间语义可证的前提下补齐该类更细粒度缺口。
