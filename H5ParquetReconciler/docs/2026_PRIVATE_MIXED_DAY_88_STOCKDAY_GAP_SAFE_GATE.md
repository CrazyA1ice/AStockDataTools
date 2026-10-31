# 2026-10-31 全历史日线剩余88条H5-only混合日期股票日键

## 来自Windows 16/16年度源审计的真实结果

2011—2026，购买Parquet有效候选日线13,916,797条，H5有效候选日线13,345,263条，重叠13,322,984条、PQ独有593,813条、H5独有22,279条。22,279=已经进入不可变私有overlay的2026-10-08/09/12/13完整缺日22,191条 + 仍未补的88个混合日期股票日键。

2016-08-25有1条。2026年有87条分布于10个混合日期：
2026-04-08=5，04-09=3，04-10=7，04-13=8，04-14=6，04-15=4，04-17=9，05-25=18，06-18=21，07-16=5，08-03=1。注意：这里实际是11个2026年混合日期，合计87条（以逐日期原审计核对，不凭描述推断）。

2026-07-16同日有4,978条重叠股票日线价格超出现有容差。虽然该日仅有5条H5独有，依然必须先隔离这5条、不能未经独立核对放入普通自动补齐流程。其它83条只是可以推进下一阶段真实精确键复核的候选，并不代表已物化。

全历史总账另有5,023条重叠价格差异、79,081条量额差异；购买Parquet现有值一律优先，H5候选单位/舍入并未全历史认证。本工具不处理2011年前的H5、分钟线或生产H5镜像。

## 新离线门禁

tools/plan-private-mixed-h5-day-gaps-offline.py 以reports中的16年历史账本及2016、2026年原始精确键扫描SAFE作为输入，重新按日计算stockday缺口，并要求原始年度SAFE文件完整SHA256与历史账本一致，严格检查22,191整日及88混合日守恒；校验历史总账明确尚未合并或激活。

只输出日期与每日期数量，绝不输出真实证券代码、原价量额、原H5整数、行情绝对路径。完全离线，不访问原H5或原购买Parquet，不创建任何私有K线，也不能激活production/private指针。混合日期与整日缺失严禁共用一个stager。

新增tests/test_plan_private_mixed_h5_day_gaps_offline.py，12项纯合成测试；PR阶段Windows尚未执行，完成测试和真实SAFE之前不能声称通过。

## Windows PowerShell（每个命令为物理单行）

第一条：拉分支并执行新12项合成门禁：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/mixed-day-h5-gap-88-candidate-gate-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/mixed-day-h5-gap-88-candidate-gate-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\plan-private-mixed-h5-day-gaps-offline.py H5ParquetReconciler\tests\test_plan_private_mixed_h5_day_gaps_offline.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_plan_private_mixed_h5_day_gaps_offline.py" -v; if ($LASTEXITCODE -ne 0) { throw "混合日期88条候选的12项合成测试失败" }; Write-Host "12项纯合成门禁通过"

第二条：新合成测试OK后，离线审核2016/2026原精确扫描SAFE和16年账本SHA（仅reports JSON，不读取市场原件）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\mixed-day-88-candidates-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-private-mixed-h5-day-gaps-offline.py --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --out $out --offline-reports-only; if ($LASTEXITCODE -ne 0) { throw "真实离线候选门禁失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.remaining_mixed_date_h5_only_stockday_candidates -ne 88 -or $r.eligible_for_next_live_key_recheck_only -ne 83 -or $r.quarantined_pending_price_disagreement_review -ne 5 -or $r.safe_to_automatically_stage_promote_or_mirror -ne $false -or $r.original_market_files_modified -ne $false -or $r.market_source_files_read_by_this_offline_gate -ne $false -or $r.private_stage_or_overlay_pointer_modified -ne $false) { throw "真实候选数/安全标志异常" }; Write-Host "候选SAFE：$out"; $r.years | ForEach-Object { $_.mixed_date_candidates } | Select-Object date,h5_only_stockday_candidate_rows,same_day_overlapping_price_disagreements,status | Format-Table -AutoSize

## 下一阶段

新增真正只读源的逐股票—日期精确键核查：只针对2016-08-25和2026年的非隔离日期，确认83个真实H5独有键在购买Parquet中不存在，独立检查源文件稳定与数值几何，之后方可通过额外显式授权生成新的private Parquet candidate stages；与已有22,191整日缺口private immutable overlay版本分开管理。2026-07-16的5个候选要隔离，不得与普通候选一起自动暂存。

2016—2026的购买Parquet原件、原Hikyuu H5、任何生产/私有活动指针、2016年前古早H5来源均保持不变。分钟线和H5镜像仍是后续独立阶段。
