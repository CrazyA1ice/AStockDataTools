# 2026-10-31 已核实的83个H5-only股票日键 → 独立私有Parquet候选分区

## 实机前置证据

- 已验收PR #188，并合并main。Windows新增13/13合成测试全部通过；真实83键验证成功。
- 本机SAFE：reports/live-mixed-day-83-keys-c8bf8ababde4.json，2016年1条+2026年82条，2026-07-16的5条隔离，购买两列ts/symbol投影扫描1,236,863行。
- 具体83个股票代码/交易日期仅存本机 work/unified_parquet/mixed_day_key_manifests/keys_c8bf8ababde4/keys.json，**不能上传GitHub/聊天**；报告中该私有文件SHA为 ba2e6a9c8360dc389efbe68bdd8d15c705184be0bdb187f3ec8e1879f6a8a585。
- 原始16年完整差集为H5-only 22,279 = 已经完成2026-10-08/09/12/13四个完整缺日的私有Parquet 22,191 + 混合日期88。5条2026-07-16仍维持隔离，不进入此暂存器。不能声称全部历史已完全对齐。

## 此PR新增工具

tools/stage-private-mixed-h5-day-83-bars.py，只执行显式 --action plan 或显式 --action stage --allow-new-private-parquet-stage，均强制 --read-only-original-market-sources。

每次重新校验完整SHA关联16年总账、2016/2026的精确源审计、88/83+5离线Gate、83条真实键SAFE和本机私有键文件，不接受不匹配的stock-day键。原市场文件stat指纹必须与上轮83键实机复核时一致；再次真实H5/PQ精确日期键扫描，确认83条H5-only键与原私有manifest完全相同，并且购买Parquet从未存在相同键。源改变、采购文件新增或任意数据校验失败即关闭，不进行暂存。

只有在所有校验通过后，读取原H5这83条日线的open/high/low/close/transCount/transAmount，按照**已有的H5候选缩放规则**（price 0.001，日线成交量×100，成交额×1000）转换为独立的私有Parquet候选，OHLC几何、数值非负有限且83行唯一；回读全表确认字段一致，再记录day.parquet SHA256和模块内manifest。标记三项换算因子全是**候选、未正式认证**，不能宣称金额精度无损，不能修改原购买Parquet，不覆盖H5，不建立H5镜像，不激活生产/私有指针。

独立暂存路径：work/unified_parquet/mixed_day_stages/mixed_<hex>/day.parquet 与 manifest.json。输出reports/stage-mixed-day-83-*.json只含总量、SHA、状态，不含实际股票/价格/成交量/金额或原源完整路径。

此暂存候选不属于已经存在的22,191根完整缺日不可变overlay版本；后续需要新的显式逻辑联合版本/只读查询验证，按购买Parquet优先、整日缺口先、混合股票日缺口后且绝不重叠，**不能直接覆盖或替换旧版本**。

新增 tests/test_stage_private_mixed_h5_day_83_bars.py，14项合成测试：SHA/私有路径约束、异常重复/隔离键、真实形状83条虚构H5转换和Parquet字段回读、计划绝不暂存、显式暂存、购买来源过期失败、源异常价格或缺记录拒绝。**Windows首轮执行14项合成测试：12项通过、1项FAIL、1项ERROR。两处测试夹具问题已在提交 00e14c0 修复（保持生产代码 fail-closed 保护）。修复版本尚待Windows重测确认；必须先14/14通过，再PLAN，最后显式STAGE。**

## Windows PowerShell，每个命令仅一行

1. 拉分支，语法检查并运行14项合成：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/stage-private-mixed-day-83-bars-20261031; if ($LASTEXITCODE -ne 0) { throw "切换私有候选暂存分支失败" }; git pull --ff-only origin feat/stage-private-mixed-day-83-bars-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\stage-private-mixed-h5-day-83-bars.py H5ParquetReconciler\tests\test_stage_private_mixed_h5_day_83_bars.py; if ($LASTEXITCODE -ne 0) { throw "语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_stage_private_mixed_h5_day_83_bars.py" -v; if ($LASTEXITCODE -ne 0) { throw "14项合成测试失败，禁止真实私有暂存" }; Write-Host "83条私有Parquet候选14项合成测试通过"

2. 测试全OK后，先在真实H5/PQ原件执行只读 PLAN。PLAN不产生私有行情分区，仍会生成模块内脱敏SAFE：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $dir="H5ParquetReconciler\work\unified_parquet\mixed_day_stages\mixed_$rid"; $out="H5ParquetReconciler\reports\stage-mixed-day-83-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-private-mixed-h5-day-83-bars.py --source-root "D:\stock" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --live-safe "H5ParquetReconciler\reports\live-mixed-day-83-keys-c8bf8ababde4.json" --private-keys "H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_c8bf8ababde4\keys.json" --stage-dir $dir --out $out --action plan --read-only-original-market-sources; if ($LASTEXITCODE -ne 0) { throw "真实83条私有候选PLAN失败，禁止暂存" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.verified_mixed_h5_only_stockday_bars -ne 83 -or $r.stage_parquet_created -ne $false -or $r.source_market_files_written -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_automatic_market_merge -ne $false) { throw "83条PLAN安全门禁失败" }; Write-Host "83条候选PLAN SAFE：$out"

3. PLAN通过后，使用**另外一个新GUID目录**显式生成全新私有Parquet候选文件，不修改任何原件：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $dir="H5ParquetReconciler\work\unified_parquet\mixed_day_stages\mixed_$rid"; $out="H5ParquetReconciler\reports\stage-mixed-day-83-complete-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-private-mixed-h5-day-83-bars.py --source-root "D:\stock" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --live-safe "H5ParquetReconciler\reports\live-mixed-day-83-keys-c8bf8ababde4.json" --private-keys "H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_c8bf8ababde4\keys.json" --stage-dir $dir --out $out --action stage --allow-new-private-parquet-stage --read-only-original-market-sources; if ($LASTEXITCODE -ne 0) { throw "真实83条私有Parquet暂存失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.verified_mixed_h5_only_stockday_bars -ne 83 -or $r.stage_row_count -ne 83 -or $r.stage_parquet_created -ne $true -or $r.source_market_files_written -ne $false -or $r.purchased_parquet_replaced -ne $false -or $r.private_or_production_active_pointer_modified -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_automatic_market_merge -ne $false) { throw "真实83条暂存安全门禁失败" }; Write-Host "83条私有Parquet候选SAFE：$out"

## 状态说明

只上传 reports/stage-mixed-day-83-*.json 或显示的汇总文字，不上传 work/ 中私有day.parquet、keys.json、manifest.json，所有源商业行情及股票键保持本地。金额舍入候选仍未获提供商规则认证。这是**安全私有候选暂存**，不等于原PQ或原H5已经统一，也不替代隔离日5条的人工分析或后续分钟线与H5镜像。
