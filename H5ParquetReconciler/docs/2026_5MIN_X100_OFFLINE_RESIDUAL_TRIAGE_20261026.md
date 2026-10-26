# 2026五分钟×100候选残余：只依赖既有JSON推导严格交叉下界

2026-10-26。输入是已由用户在本机生成的`h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json`；本阶段**不扫描H5和Parquet原始行情、不读取任何OHLCV值、不依赖超大5min索引，也不向GitHub上传付费行情**。

## 一、实测边际数量和不能随意猜测的交集

在2026-09-24、28、29、30四天的1,065,216个已匹配键里，假设H5五分钟成交量×100后，按**原来严格容差**，来源报告给出：
- V（成交量差异）= **3,097**；
- A（成交额差异）= **2,812**；
- P（至少一项OHLC价格差异）= **1,893**；
- U（V、A、P任一字段差异）= **3,440**；
- 全部一致（原容差、换算假设条件下）= **1,061,776**；
- 原口径成交量冲突1,060,937，换算候选消除1,057,840条，新增0。

这里的`V/A/P`是**边际个数**，不能直接相加当作互不重叠的三类，更不能称3,440条全部是成交量差异。设各自为集合，利用严格的集合容斥下界：

| 量价交叉类别 | 来源现有统计能证明的界限 |
|---|---:|
| **任一量价残余冲突 U** | **3,440（精确）** |
| 不涉及V、只涉及P或A | **343（精确）** = U−V |
| 同时涉及V和A | **≥2,469** = V+A−U |
| 同时涉及V和P | **≥1,550** = V+P−U |
| 同时涉及A和P | **≥1,265** = A+P−U |
| 同时涉及V、A、P三项 | **≥922** = V+A+P−2U |
| **仅成交量V** | **0～628**（上界 U−max(A,P)） |

这些是**从边际统计必然推导出的下界/区间，不是逐K线的真实Venn交集**。例如同时涉及V/A/P至少922条，但没有逐条字段标记，就不能认定刚好922条。工具在JSON内保留`all_field_overlap_bounds_not_exact_intersections=true`和`no_field_level_raw_keys_available_from_this_report=true`。

## 二、代码前缀和交易日的可定位范围

- 候选成交量残余按代码前缀分别：SH_other **1,742**、BJ **806**、SH688/689 **549**、SZ300/301 **0**、SZ_other **0**。SZ两个组只存在金额差异计数2和1，合计3条已知仅非量差异的下界。
- 按交易日：2026-09-24 **744**、09-28 **910**、09-29 **832**、09-30 **611**。**9月28日的成交量残余绝对数量最多**，但这不是价格+金额+成交量去重后的精确总数；因此不能把它直接称为“全部冲突最多日”。
- 工具对每一个互斥的**前缀组**以及**交易日**，用各组V/A/P和总共343个非成交量增量推导本组`candidate_any_mismatch_lower_bound`、`candidate_any_mismatch_upper_bound`，并检查全组的匹配键、每类差异和日期volume计数都和母报告守恒；不虚构分组精确U值。
- 切入点：如果后续确需实测精确字段联合分布，优先从残余规模最大的SH_other、BJ、SH688/689与9月28日开展**少量股票+单日有界检查**，可使用已有`diagnose-5min-alignment.py` / `plan-5min-readonly-union.py`工具及已验证覆盖索引。但当前没有足够字段级每证券证据来指定“必然有冲突的样本代码”，不应臆造名单。

## 三、Windows操作：只读JSON，预计无需大型I/O

本工具新增于`tools/triage-5min-x100-residual-offline.py`；有`tests/test_triage_5min_x100_residual_offline.py`纯合成回归测试，验证严格守恒、交叉下界、分组上下界、错误元数据及无OHLCV读写。

仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\triage-5min-x100-residual-offline.py --report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json" --out "reports\h5-parquet-5min-2026-09-24-30-residual-triage.json"
```

输入文件名如在本机有所差异，只修改`--report`后路径，**不用重新运行双源年度/五分钟扫描**。输出仅在模块`reports/`内，新文件不能覆盖原JSON。上传新生成的`h5-parquet-5min-2026-09-24-30-residual-triage.json`即可继续下一步量价冲突精确分类的分层计划。

本阶段不声称从汇总统计自动识别缺陷供应商；仍需核对成交量字段正式单位、价格/金额规则、上市证券状态和差异保留方案。不能自动选择一个来源覆盖另一个，`safe_to_automatically_union=false`。
