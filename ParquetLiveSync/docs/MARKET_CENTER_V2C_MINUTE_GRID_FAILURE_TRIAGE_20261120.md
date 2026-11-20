# V2-C 第一段：运行状态解释与只读分钟标签时间格分析

2026-11-20。基于 V2-B2：用户已验证70/70离线测试、两只股票在2026-11-19日线的真实只读抽查与新GUI。

## 11月20日晚上异常的准确边界

运行总览截图：已提交最新日2026-11-20；本次执行PARTIAL；八周期行情与板块的本轮本地校验PASS；除权PARTIAL；财务运行退出码1；财务待审45项。勿据此断言全部行情损坏。

原 market_daily_verification.py 的除权逻辑：当 exit=0，存在合格回执且 next_batch_required=true 时，data_validation=PARTIAL；这表示旋转更新本批已通过但后续还有批次，**不代表数据异常**。财务 exit=1 才是已确认的本轮执行失败，根因仍需核对本次同源日志。QMT CONNECTED 是本次开始前的预检，不保证财务阶段成功；待审45不等于本次新增45只。

已改 GUI 的运行总览文案：成功但待轮换的除权阶段显示“本批通过，轮换仍有后续批次（非本批失败）”；财务非零退出码显示“请查看本次阶段日志”。

下面给用户可复制的一行 Windows PowerShell 命令（纯读取正式私有回执和除权/财务日志；不会触碰QMT、生产锁或行情文件）：

    $ErrorActionPreference="Stop"; $work="D:\ChatGPT\AStockDataTools\ParquetLiveSync\work"; $receipt=Join-Path $work "last-afternoon-unified.json"; if(-not(Test-Path -LiteralPath $receipt -PathType Leaf)){throw "LATEST_RECEIPT_MISSING"}; $j=Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json; Write-Host ("RUN_STATUS="+$j.status+"; CHINA_START="+$j.china_start); Write-Host "RUN_ERRORS"; $j.errors | ForEach-Object {Write-Host $_}; Write-Host "VALIDATION"; if($null -ne $j.validation){$j.validation | ConvertTo-Json -Depth 8}; $prefix=[IO.Path]::GetFullPath($work).TrimEnd('\')+'\'; foreach($name in @("ADJUSTMENTS_ROTATING","FINANCIAL_DAILY")){$stage=$j.stage_records.$name; if($null -eq $stage){Write-Host ("STAGE_NOT_FOUND="+$name); continue}; Write-Host ("STAGE="+$name+"; EXIT="+$stage.exit_code); $p=[string]$stage.log_path; if([string]::IsNullOrWhiteSpace($p)){continue}; $full=[IO.Path]::GetFullPath($p); if(-not $full.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw "STAGE_LOG_OUTSIDE_WORK"}; if(Test-Path -LiteralPath $full -PathType Leaf){Write-Host ("LOG_TAIL="+$name); Get-Content -LiteralPath $full -Encoding UTF8 -Tail 90}else{Write-Host ("STAGE_LOG_MISSING="+$name)}}; Write-Host "READONLY_DIAGNOSIS_COMPLETE"

## V2-C 分钟标签时间格首段

新增 market_center_v2_minute_grid.py，纯内存分析5个分钟周期：1/5/15/30/60min。比较开盘时间标记 OPEN 与收盘时间标记 CLOSE 两组假设：09:30–11:30 和 13:00–15:00 作为两段连续交易区间；OPEN 包含每周期开始时点，CLOSE 包含每周期结束时点。参考点数分别240/48/16/8/4，**参考时间格不是已证明的QMT/TDX真实标签合同或交易所完整性**。

同时对原有V2-B的“单日分钟行数不同于240/48/16/8/4”做安全纠偏：此计数仅出现在 standard_bar_count_difference_candidate，不会单独将物理状态设置成 ANOMALY_OBSERVED；只有重复键、OHLCVA明显异常等真实物理检查发现的问题才保留异常状态。这避免239条数据被自动误导为数据损坏或可补缺失。\n\n针对每只选择的股票和分钟日期，输出：
- minute_grid_observations：股/周期/标签日/观察到的唯一时间戳数；
- 候选最接近的 OPEN/CLOSE 参考标签（若两者距离相同则 AMBIGUOUS，不强选）；
- 与参考标签的候选差异计数及最多8个样本、连续交易区间外标签与非整分钟标签数；
- 无行时输出 NO_MINUTE_ROWS_EXPECTATION_NOT_ESTABLISHED，不虚构“缺240条”；
- 均标 minute_label_complete_certified=false、grid_profile_source_certified=false、allowed_to_backfill=false、市场写入false、QMT调用0。

这层分析直接挂在原V2-B2严格限范围的Parquet只读审计中，并在新版GUI核验结果的可展开原始证据中显示。原来的交易日与股票有效性未认证状态不变。1分钟239条不等于“确认缺一条”，241条也不能直接删掉09:30时标；例如09:25竞价标签可能被某供应商合法包含，故仅报告观察差异。

安全限制保持：只看显式指定的最多20股、最多31日、32分区、160行组、250万候选行，单股日周期的独立分钟时间标签最多512；保留19:55–20:20（北京时间）计划任务优先窗口及45秒只读扫描截止。冻结范围仍为2026-11-19，**本版分钟审计尚未批准查询11月20日**。11月20日故障从同一次私有回执和阶段日志排查。

## Windows 验收建议

在当前V2-B2旁建立另一个 detached worktree，避免覆盖已验收代码。依次运行 V2-A/B/B2 三组合成测试以及新增 market_center_v2_minute_grid.py 测试。尤其关注：5周期 OPEN/CLOSE 样本，239/240/241条1分钟，午间/竞价候选标签、跨日期拒绝、空数据不能认证缺失、禁止任何自动回填。然后避开北京时间19:55—20:20、在正式自动任务结束时，选择2026-11-19、000001.SZ、1min，先作一次小范围只读核验，并在GUI展开原始时间格信息。用户提供运行日志后再判断可否推进下一阶段。

**不执行的事项**：不改正式20:05任务、原统一更新器、私有QMT/H5/Parquet文件，不重跑全量，不直接覆盖除权/财务，不允许任何缺口候选转为执行计划。只有收到财务失败同次日志后，才决定是否作有针对性的修复或追溯。
