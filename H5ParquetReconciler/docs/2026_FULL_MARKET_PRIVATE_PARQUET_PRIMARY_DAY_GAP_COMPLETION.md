# 2026-10-30：恢复既定主线——购买Parquet只读为主，补入原H5独有日线，再做独立H5镜像

## 最终数据优先级与不变量

1. **绝不能改写用户购买的任何原始`AllCycleAStockData/{day,1min,5min}` Parquet文件**，包括增量行、覆盖、修改列定义、重存文件。它始终是有键时的唯一优先源。
2. 仅当经过原始H5、购买Parquet完整市场差集报告、逐日期gate、源实时核对、SHA/Parquet数据回读**同时**证明整日购买数据完全缺失且原H5存在合法整日证券键，才允许把原H5当日**复制为全新隔离的私有Parquet分区**。不是直接插入原购买Parquet。
3. 购买Parquet原文件 + 全部SHA验证过的H5-only新日期私有分区组成统一的**逻辑Parquet主数据视图**；可通过显式不可变SHA加载。未授权任何private-active pointer修改、生产默认查询路由修改。
4. 日线**不是**分钟线：本轮仅完成先前已审计窗口2026-09-01～10-28的`day`缺口，尚需逐期做`5min`和`1min`真实键、时间标签/量额一致性与缺口核对；也不代表2011～2026所有年份全部完备。
5. 只有在**整个目标范围**统一Parquet主线验收完毕、Hikyuu H5金额/成交量物理单位和整数舍入转换检验通过后，才从统一Parquet**生成全新私有原生H5镜像**。保留原H5，不覆盖、不调用生产mirror。H5数值`amount raw*1000`、`volume raw*100`目前仍是候选诊断关系，不是无损逆转换认证。
6. 暂停本期的通达信落点搜寻和更新自动化；以后用户自行更新通达信盘后真实数据时，再设计其只读源核查与后续统一Parquet增量。

## 当前已真实审核的2026年日线完整缺日依据

用户此前的本机日线audit：2026-09-01～10-28，H5 138,641、购买Parquet 116,567、双方匹配键116,450、购买独有117、H5独有**22,191**，双方重叠OHLC按已有容差差异为0，仍有部分成交量与金额差异（Parquet有键时永远胜出）。

H5独有仅对应**4个购买Parquet整日完全无键的日期**：2026-10-08（5,546根）、10-09（5,547根）、10-12（5,549根）、10-13（5,549根），合计`5546+5547+5549+5549=22191`。审计源报告`reports/day-coverage-20260901-20261028-v1.json`与SHA绑定gate `reports/parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json`已在本机验证过；新命令会**再次核查真实这两个文件SHA、原购买源确实缺失、所有4日H5行数、所有私有Parquet schema/日期键/唯一股票、文件SHA**，而不是仅凭上面历史摘要执行。

这是完整交易日的**H5差集副本**，并不证明外部原始来源的单位真实性，也不代表2026年10月14日之后有新记录（用户已验证截至2026-10-13三个数据来源均未更新）。

## 新的全市场4日收口脚本

`tools/complete-private-parquet-primary-day-gap-set.py`包装现有三个经过测试的`plan-parquet-primary-day-bootstrap-offline.py`、`stage-h5-only-day-to-parquet.py`、`build-parquet-primary-day-overlay.py`：

- `--action plan`：强制验证报告和gate的完整日期键守恒、零混合日H5缺口、总日线行数与每日期一致；在`work/unified_parquet/staging/`仅扫描**第一层**已有私有暂存Parquet，逐份复核原始报告/gate SHA、schema、日期和全部行键/Parquet SHA。输出哪些日期已暂存，哪些仍缺少；**不写私有Parquet、版本文件或原行情**。
- `--action complete --allow-new-private-parquet-stages`：对缺失的完整日期调用既有`STAGE.stage()`，逐日执行原H5/购买Parquet真实安全复核、生成全新的`work/unified_parquet/staging/complete-day-YYYYMMDD-v1/day.parquet`（以及私有manifest），已验证旧日期分区原样复用；不得覆盖已有目录。生成新文件过程前中后核对原始市场源大小/mtime，不改原文件。**若审计报告或源发生变化，拒绝继续**。
- 所有完整日期就绪后再调用旧`OVERLAY.prepare()`：一次完整实盘whole-day 4日期核对、验证全部私有分区及总行数，登记SHA内容寻址、**未激活的不可变统一私有Parquet逻辑版本**。它**不修改**原购买Parquet/原H5，不会改变生产或任何active指针。
- 新SAFE只在`H5ParquetReconciler/reports/`记录4天审计行数、已有/新增日期、累计H5 gap行数（期待22191）、报告SHA、预备版本SHA和不可生产镜像声明；没有股票代码、价量额或市场源绝对路径。真实付费/原H5价格仍只在`work/`私有Parquet文件。
- 源检查仅为stat指纹和之前audit的回算重核；**不是交易所完整行情或供应商文件级内容SHA认证**。如出现未注册混合日期缺口，拒绝该整日收口流程，必须改走逐股日键审计，不能偷偷删掉不合格行。
- 本工具禁止自动私有active pointer启用、正式生产查询切换、生产原生H5镜像，H5量额仍未完成独立认证。

## Windows：先测试，再正式plan和complete（均为单行命令）

预期入口`D:\\stock`，源日线报告文件名如上；命令行必须从仓库根`D:\\ChatGPT\\AStockDataTools`执行。旧私有stage目录名称可以不同，工具按精确来源SHA找到后复用；如果同一个日期发现两个同样合法的stage会保守拒绝而不擅自选一个。

**第一条：测试并生成真实全市场4日plan（只读）**

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/parquet-primary-complete-four-h5-gap-days-20261030; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/parquet-primary-complete-four-h5-gap-days-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_complete_private_parquet_primary_day_gap_set.py" -v; if ($LASTEXITCODE -ne 0) { throw "12项新测试失败，不审计真实源" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-complete-day-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\complete-private-parquet-primary-day-gap-set.py --action plan --root "D:\stock" --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --out $out --original-sources-read-only; if ($LASTEXITCODE -ne 0) { throw "全市场4日候选plan失败，停止" }; $report=Get-Content $out -Raw | ConvertFrom-Json; if ($report.audited_complete_h5_only_days -ne 4 -or $report.audited_complete_h5_only_day_rows -ne 22191) { throw "非先前验收的4日22191行，禁止物化" }; Write-Host "plan脱敏SAFE：$out"
```

**第二条：明确执行有审计证据的私有Parquet补齐和统一逻辑版本（没有生产写入）**

```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-complete-day-apply-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\complete-private-parquet-primary-day-gap-set.py --action complete --allow-new-private-parquet-stages --root "D:\stock" --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --out $out --original-sources-read-only; if ($LASTEXITCODE -ne 0) { throw "4日全市场私有Parquet补齐/版本准备失败" }; $report=Get-Content $out -Raw | ConvertFrom-Json; if ($report.audited_complete_h5_only_days -ne 4 -or $report.audited_complete_h5_only_day_rows -ne 22191 -or -not $report.prepared_immutable_overlay_sha256) { throw "私有版本不满足4日22191行门禁" }; Write-Host "只读原购买Parquet已保持不变；全市场4日私有统一Parquet版本SHA：$($report.prepared_immutable_overlay_sha256)；脱敏SAFE：$out"
```

如果报告路径名不匹配、旧stage已损坏、某日源由后续下载更新、验证失败，请回传**错误信息**，不要自行改购买源文件或强制覆盖旧stage；工具可针对真实输出问题再安全处理。

## 后续：真正完整的双格式对齐工作

完成这4个真实日期的私有Parquet并生成统一逻辑版本后，下一阶段先对整段2011～2026的**日线**按年分块运行购买主线/H5仅缺日审计，检查是否还有混合日股票级差集；再做`5min`、`1min`按真实时间标签与完整网格的缺口盘点及独立私有分区。不能把跨历史5min/1min价格数量差异擅自覆盖购买Parquet。

只有当目标范围的统一Parquet完全验收，且H5原生整数OHLCVA金额单位/取整的无损或可接受误差证据、合成镜像/回读门禁通过，才允许**创建独立新H5镜像**；仍需显式授权才谈实际替换Hikyuu生产数据，不允许改写原H5文件。
