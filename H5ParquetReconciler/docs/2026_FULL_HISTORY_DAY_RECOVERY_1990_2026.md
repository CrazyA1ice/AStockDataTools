# 2026-11-03：补齐历史1990—2010日线至统一Parquet候选版（先处理日线）

## 首先纠正之前错误的范围结论

此前2011—2026年16年的**14,137,981条**统一日线购买优先物理Parquet与原生H5镜像已经Windows完整整数回读成功，但**不是全部历史日线**。更早1990-12-20—2010-12-31原H5还有SH 2,056,452 + SZ 1,625,875＝**3,682,327条**候选日线，已在用户Windows实际完整写出21个独立RAW Parquet，并独立完成1990—2010全21年原生日线原整数、SHA、年度键与来源的对账：`reports/pre2011-full21-verify-9bba81ed3c33.json`。原购买day Parquet全24个文件、139 rowgroup的时间戳footer最早2011-01-04（限定该已扫描目录）。**这些历史记录已经提取了，并非缺少源H5扫描。**

**暂不能直接写生产标准统一日线**：原H5字段是unsigned整数（`openPrice,highPrice,lowPrice,closePrice,transCount,transAmount`），而2011年后的购买物理schema是`ts,trading_date,symbol,source_symbol,open,high,low,close,volume,amount,value_source`及OHLCVA Float64。2025/26买源配对样本曾支持价格÷1000、量×100、额×1000，**不能直接推广1990—2010**。用户已完成的21年VWAP倍率矩阵显示：原生量额双正3,682,262条，原生`amount*10000/count`可落入RAW高低价范围的候选共约3,673,987条；1990/1991/1992年倍率明显不同，1990仅24条不宜盲补。以前的7条Hikyuu C++历史读取只验证原生整数/解码，并未证明和购买源的物理交易量额、历史证券身份、复权水平一致。

## 本轮交付（GitHub分支）

新增 **真实数据转换程序** `tools/stage-pre2011-day-normalized-candidates-with-quarantine.py`：
- 每次按年从已经SHA验证的私有历史RAW而不是重新打开原H5读入，建立**购买Parquet同字段类型**的年度OHLCVA **候选Parquet**：日期统一北京时间0点，价格原整数÷1000、量×100、额×1000，`value_source=h5_pre2011_numeric_hypothesis_not_vendor_certified`。
- 只有RAW OHLC有效、成交量金额非零且整数VWAP候选F=10000处在原H5日内高低价±0.5%内的记录进入候选；此门禁仅说明**内部算术一致，不是供应商量纲认证**。其余早期异制度、单边零量额、OHLC异常或其他不符，**源原始整数一条不丢**地写入单独`source_native_quarantine.parquet`，注明拒绝原因，不伪造价格/成交额或删除历史。
- 对同一历史股票日期严格去重，年度总行数守恒，候选与隔离Parquet完整全字段回读/哈希对比，输出各自文件SHA和行数；不会覆盖原购买Parquet、原H5、21个原生RAW及已验2011—2026年16个分区。失败留下隔离数据，不自动销毁。

新增 **全历史候选逻辑清单/断点续跑器** `tools/build-1990-2026-private-day-candidate-version.py`：
- 一次在Windows自动依次处理1990—2010全部21年，**先一次性**核对原始RAW来源SAFE、21个Parquet SHA，不为每年反复校验同样21份文件；
- 与既有2011—2026日线**已验收的16年版本SHA `bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05`**关联，不重新写已有14137981条；历史新候选+隔离=3,682,327，全时期来源账面合计17,820,308；
- 同一个run-id中断后可以复用已经完成的年度SAFE/SHA，残缺年度用隔离attempt ID重新写，保留旧残缺文件用于审计；21年全部完成才发布未激活版本SAFE；
- 这是**候选清单，不是已经发布的1990—2026统一Parquet**，不能直接供生产Hikyuu/选股消费。需下一阶段真实数据购买量纲、历史证券身份/复权与隔离处理验证后建立正式完整版，并校验全部17,820,308条是否可纳入（不成立的历史非A股或错误原数据必须留在隔离/原生历史层）。

新增2个实际合成文件转换测试+2个离线完整历史/恢复测试，总计**4个聚焦用例**。代码已提交，**尚未通过用户Windows实测**，不能声称新统一历史完成。

## 单行PowerShell：一次更新/四测试/运行21年候选转换并输出来源账

```powershell
cd D:\ChatGPT\AStockDataTools; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; $ok=$false; for ($i=1; $i -le 3; $i++) { git -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -eq 0) { $ok=$true; break }; if ($i -lt 3) { Start-Sleep -Seconds 5 } }; if (-not $ok) { throw "GitHub连接失败；保留本地已验数据，禁止运行旧版脚本" }; git merge --ff-only FETCH_HEAD; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; git merge-base --is-ancestor c8b6a200d63732e1354d5f388b7f1e0e777ac1ab HEAD; if ($LASTEXITCODE -ne 0) { throw "未取得历史日线恢复代码" }; $py=".\.venv\Scripts\python.exe"; & $py -m py_compile H5ParquetReconciler\tools\stage-pre2011-day-normalized-candidates-with-quarantine.py H5ParquetReconciler\tools\build-1990-2026-private-day-candidate-version.py; if ($LASTEXITCODE -ne 0) { throw "脚本语法检查失败" }; & $py -m unittest discover -s H5ParquetReconciler\tests -p "test_stage_pre2011_day_normalized_candidates_with_quarantine.py" -v; if ($LASTEXITCODE -ne 0) { throw "历史日线候选真实Parquet写盘合成测试失败" }; & $py -m unittest discover -s H5ParquetReconciler\tests -p "test_build_1990_2026_private_day_candidate_version.py" -v; if ($LASTEXITCODE -ne 0) { throw "历史全范围分年断点恢复合成测试失败" }; $old="H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json"; $modern="H5ParquetReconciler\reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json"; if (-not (Test-Path $old -PathType Leaf) -or -not (Test-Path $modern -PathType Leaf)) { throw "本地21年RAW或16年现代SHA版本SAFE缺失，不能造新历史" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-day-historical-candidates-and-2011-2026-union-$rid.json"; Write-Host "历史日线重建任务ID：$rid（中断时请保存它；同一ID可以跳过已验收年份并隔离重试残缺年度）"; & $py H5ParquetReconciler\tools\build-1990-2026-private-day-candidate-version.py --full21-safe $old --modern-version-safe $modern --modern-version-sha256 bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05 --run-id $rid --out $out --build-full-history-day-candidate-version; if ($LASTEXITCODE -ne 0) { throw "历史候选转换尚未完成：保留任务ID $rid，继续用同一ID重试，不删除任何已验收数据" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.raw_1990_2010_h5_rows_preserved -ne 3682327 -or $r.modern_2011_2026_accepted_private_rows -ne 14137981 -or $r.all_1990_2026_source_rows_without_overlap -ne 17820308 -or $r.historical_candidate_vendor_units_or_corporate_actions_certified -ne $false -or $r.original_market_files_or_previous_private_shards_modified -ne $false -or $r.private_active_pointer_modified -ne $false) { throw "历史与现代日线总数/安全状态不一致" }; Write-Host "PASS：1990—2010年原生RAW合计3,682,327条已全部分类，不合格原样隔离；2011—2026年14,137,981条未重建"; Write-Host "历史标准结构候选=$($r.purchase_schema_historical_hypothesis_rows)；原生完整隔离=$($r.historical_native_raw_quarantined_rows)；合计来源=$($r.all_1990_2026_source_rows_without_overlap)"; Write-Host "注意：仍是未认证候选版，不可替代生产统一Parquet！SAFE：$out"
```

若GitHub网络失败会立即停止，不会改变源数据；若21年任务中断，重新运行时**请用之前打印的run-id手工指定原值**（不能再次生成随机ID），已经完成年份将按SHA跳过，残缺年份隔离重试。只有候选与隔离合计完全守恒才发布SAFE。若希望无需PowerShell再手输，下一阶段把“日线历史补齐/隔离”接入统一GUI，保留单次确认权限与实时进度；不可在验收前默认生产切换。

## 形成真正完整统一Parquet前仍需做到

1. 完成历史候选年SAFE，并从隔离名单归类：1990—1993量额制度差异、早期非标准交易、资金单位和复权问题；购买源2011后不重算不覆盖。
2. 使用Hikyuu 2.8.1真实历史驱动输出的量额定义+购买文件说明与重叠样本核对可用的实际量纲，考虑不同年份/证券的不同编码；**内部F10000命中不得冒充确定单位**。
3. 基于历史身份信息判断SH/SZ早期股票及退市代码是否A股，而非仅看SH/SZ代码前缀；保留不可认证记录的原生RAW但不作为无条件选股交易数据。
4. 将实际合格的历史分区**版本化并入**2011—2026现有物理schema，完成日期唯一键/现金额合法/跨年度源SHA/所有行回读，统一历史起点由实际接受的最早交易日决定；然后才更新正式只读查询入口与H5日线镜像。已有2011—2026旧镜像不能作为更新的最终H5。
