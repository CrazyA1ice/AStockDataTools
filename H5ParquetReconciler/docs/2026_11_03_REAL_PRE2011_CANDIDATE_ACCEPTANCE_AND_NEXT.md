# 2026-11-03 Windows真实历史DAY候选写盘通过：下一步原因审计而非重复转换

## 已在用户本机通过，禁止重新物化

Windows执行 `run-full-history-day-candidates.ps1 -Run` 真实回执：2+2项聚焦测试全部PASS；run ID `e1050fabe5b0`；写出21年（1990—2010）购买字段**未认证**候选 Parquet `3,673,987` 行和无损原生整数隔离 Parquet `8,340` 行，**合计3,682,327**；旧16年购买优先已验日线 `14,137,981` 行未重新物化/没有覆盖。1990—2026全来源账 `17,820,308` 行。

真实未激活版本 SAFE `reports/pre2011-day-historical-candidates-and-2011-2026-union-3c808c8da646.json`。**不要提交或公开真实Parquet/购买股价**，本机只上传脱敏原因/计数报告。

| 年份 | 购买字段候选（未认证） | 完整RAW隔离 |
| --- | ---: | ---: |
| 1990 | 0 | 24 |
| 1991 | 323 | 1,720 |
| 1992 | 2,366 | 3,526 |
| 1993 | 19,783 | 583 |
| 1994 | 52,295 | 119 |
| 1995 | 57,765 | 1,083 |
| 1996 | 75,424 | 227 |
| 1997 | 123,414 | 5 |
| 1998 | 153,758 | 4 |
| 1999 | 169,606 | 6 |
| 2000 | 189,727 | 4 |
| 2001 | 216,273 | 32 |
| 2002 | 226,812 | 63 |
| 2003 | 246,031 | 255 |
| 2004 | 268,701 | 202 |
| 2005 | 272,218 | 305 |
| 2006 | 253,935 | 53 |
| 2007 | 289,448 | 68 |
| 2008 | 324,591 | 39 |
| 2009 | 339,123 | 21 |
| 2010 | 392,394 | 1 |
| **总计** | **3,673,987** | **8,340** |

**早期风险集中**：1990—1992就隔离5,270行（全部隔离的63.2%），1995另有1,083。完整候选占历史RAW的99.77%，但VWAP内部自洽命中并非历史物理单位/复权/股票身份认证。1990没有任何行被允许按现代假设进入候选；全部24行仍可通过原生整数隔离读取，绝不能填造价格。

## 本轮新工具：不再写行情，只重验和分层登记

新增 `tools/audit-full-history-day-quarantine-and-catalog.py`：接受本机刚产生的全历史候选 SAFE，预先以SHA256固定其内容；复用已验21年历史RAW来源校验、既有16年Parquet物理版本校验、21份年度报告与候选+隔离文件SHA/Schema/Parquet行数检查；每年仅读取**隔离原因列** `quarantine_reason`，按原因汇总校验与各年度原报告一致。最终仅产生 `reports/*.json`（年份/计数/分类/SHA，不含股票代码和实际量价）。输出两个强制分层：2011—2026已验物理层 vs 1990—2010未认证候选及原生整数隔离层；`ready_for_production_query=false`，**不激活生产/不重建任何行**。

### 推荐：更短的一条Windows命令（无需重跑历史转换）

已新增 `run-day-catalog-audit.ps1`，会自动完成源码更新后的四项测试、SHA重验和8,340条隔离原因分类。**仅访问已经完成的私有21年RAW/候选/隔离Parquet，不会再写入3,682,327条市场数据，也不会激活正式行情。**

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-day-catalog-audit.ps1; if ($LASTEXITCODE -ne 0) { throw "历史21年隔离原因审计或SHA验收失败；原数据保持不变" }
```

下面保留等价的**手工展开参数版**，仅供审计与排错使用；正常运行短命令即可。

### 展开版Windows单行PowerShell

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-full-history-day-quarantine-and-catalog.py H5ParquetReconciler\tests\test_audit_full_history_day_quarantine_and_catalog.py; if ($LASTEXITCODE -ne 0) { throw "审计脚本语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_full_history_day_quarantine_and_catalog.py" -v; if ($LASTEXITCODE -ne 0) { throw "四项年度隔离原因测试失败，未运行真实报告审计" }; $v="H5ParquetReconciler\reports\pre2011-day-historical-candidates-and-2011-2026-union-3c808c8da646.json"; if (-not (Test-Path -LiteralPath $v -PathType Leaf)) { throw "本机21年真实候选版本SAFE丢失" }; $sha=(Get-FileHash -LiteralPath $v -Algorithm SHA256).Hash.ToLowerInvariant(); $id=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-historical-reject-reasons-catalog-$id.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-full-history-day-quarantine-and-catalog.py --candidate-version-safe $v --candidate-version-sha256 $sha --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --modern-version-safe "H5ParquetReconciler\reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json" --modern-version-sha256 bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05 --out $out --audit-sha-bound-private-only; if ($LASTEXITCODE -ne 0) { throw "真实21年历史目录SHA或隔离原因验收失败，原数据不变" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.historical_purchase_schema_unverified_candidate_rows -ne 3673987 -or $r.historical_native_quarantined_rows -ne 8340 -or $r.all_history_source_rows_accounted -ne 17820308 -or $r.ready_for_production_query -ne $false) { throw "历史真实计数或生产门禁异常" }; Write-Host "PASS：1990—2026分层来源全数保留，隔离原因SHA审核完成；下一步只调查原因与历史量纲"; Write-Host "SAFE：$out"; $r.all_historical_quarantine_reasons | Format-List
```

### 随后真正的数据库交付

1. 若新审计通过，先按`quarantine_by_reason`归类1990—1992、1995的早期量纲问题，做有来源证据的**按时代认证**而非全历史统一倍率；不把未认证候选推送到生产。
2. 分层只读消费端可立即对已验2011—2026分区开放；1990—2010用明确实验候选或原生RAW视图（消费者显式选择），不强行把不同schema合并。
3. 日线认证处理只访问异常/待判定分类，不再重跑3,682,327条原H5提取或14,137,981条旧分区。
4. 日线分层查询交付后，回到已有分钟GUI批量补齐并执行 `tools/report-verified-unified-minute-progress.py` SHA去重统计；15/30/60分钟及周/月优先沿用购买Parquet。最终发布完整周期索引、不可变版本、真实日期覆盖及异常列表。

**新增审计程序/4项离线测试尚待Windows首次执行，不能仅因GitHub提交就称验收成功。**
