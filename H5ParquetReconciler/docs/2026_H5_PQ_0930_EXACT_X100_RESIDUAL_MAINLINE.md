# 2026-10-28：H5↔Parquet真实单日day/5min完整核对；×100候选的精确残余字段组合

## 已获得的真实数据（用户Windows生成，不是推测）

输入：`reports/h5-pq-overlap-20260930-day5min-v1.json`（以及同名.md）。
审计状态`complete`，`results['day/2026']`、`results['5min/2026']`均`scan_complete=true`、`issues=[]`；
代码范围`a-share-candidate`只是代码前缀的股票候选过滤，未经证券类别认证。
源文件未修改；本次检查窗口**仅**2026-09-30，不是2026全年。

| 周期 | H5 | Parquet | 交集 | H5独有 | Parquet独有 | 原始量价冲突 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| day | 5,550 | 5,560 | 5,550 | 0 | 10 | 1,241 |
| 5min | 266,400 | 267,408 | 266,400 | 0 | 1,008 | 265,181 |

day共有记录5,550条的OHLC价格字段冲突为0，1,241条冲突全部属于量额；
5min价格冲突为403条，量额冲突265,181条（交集可能重叠，不能将两个数字相加）。
5min独有的1,008条来自21个Parquet有48根、H5完全无同日键的股票日，
没有识别到双方都有但局部缺键的股票日。只有1个交易日，
不能据此断定2026全年H5绝不更全，也不能认定这21组均为真实交易缺数。
day独有10个股票日与5min独有21个股票日是**不同周期的集合**，
未对证券同日集合逐个求差，不能断定11个差额都属于什么证券类型。

## 五分钟成交量×100候选证据

在266,400条同证券/同五分钟候选时标交集上：

| 指标 | 实测数量 |
| --- | ---: |
| 未调整原口径成交量冲突 | 265,181 |
| 假设Parquet volume == H5 5min transCount×100后成交量冲突 | 611 |
| 原冲突被候选消除 | 264,570 |
| 原已匹配被候选破坏 | 0 |
| 不改价格/金额规则的候选综合量价冲突 | 692 |
| 六字段均在现有诊断容差内的候选K线 | 265,708 |

购买Parquet/H5成交量比值（双方均非零）的分布，约
264,874根在100倍的±1%附近，仍有306根归入other。
该比例只是来源单位候选，不代表交易所或数据供应商已经确认计量口径。

## 精确残余8类互斥字段组合——不是推测上下界

源主核对工具已经在内存比对时输出`exact_residual_field_mask_counts`、
`exact_field_mask_by_day`、`exact_field_mask_by_prefix`。
该报告完整包含这些字段，可以严格核对8类计数总和、各字段
边际计数以及按前缀/日期分组守恒：

| 互斥类别（×100候选后） | 条数 |
| --- | ---: |
| 无任何量价冲突 | 265,708 |
| 仅成交量 | 29 |
| 仅成交额 | 3 |
| 仅价格 | 77 |
| 成交量+成交额 | 257 |
| 成交量+价格 | 22 |
| 成交额+价格 | 1 |
| 成交量+成交额+价格 | 303 |

各类加总266,400；含volume的4类之和611，含amount的4类之和564，
含price的4类之和403，非无冲突7类之和692。
此前的离线triage工具只适用于单一`5min/2026`分区，且只提供
未知交集情况下的上下界。在当前真实两周期报告中，
**已有精确字段掩码时再估计上下界反而会损失信息**。

## 已对工具做针对性完善

修改`tools/triage-5min-x100-residual-offline.py`：

- 允许既有单独5min报告，或**相同年份、起止日期、候选证券范围**且
  day和5min分区均完整通过的两周期报告；多年份/额外周期/混用日期拒绝。
- 有完整8类精确字段掩码时，逐组核对总计、量额价边际、
  按交易日与代码前缀的分组计数；矛盾/部分缺失立即报错。
- 精确数据以`verified_exact_disjoint_field_masks`独立输出；
  保留旧版上下界兼容老报告，没有精确掩码绝不伪造。
- 仅离线读取已经生成的安全JSON，不重新扫描购买行情，
  不修改H5/Parquet/生产数据，不批准×100候选。

### Windows运行命令——每段PowerShell都是物理单行

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
```

先运行修改过的10项合成测试（本轮Windows尚待验收）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_triage_5min_x100_residual_offline.py" -v
```

完全离线读取你已有的完整两周期JSON生成精确归因：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\triage-5min-x100-residual-offline.py --report "H5ParquetReconciler\reports\h5-pq-overlap-20260930-day5min-v1.json" --out "reports\h5-pq-20260930-x100-residual-exact-v1.json"
```

## 下一步：独立验证×100候选，不应先做生产换算

现有工具可针对同日分别运行**来源内部**day↔5min volume守恒：

**H5内部（2026-09-30），仅H5源，输出新SAFE JSON：**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-30 --to-date 2026-09-30 --read-only --out "reports\h5-internal-day5min-volume-20260930-v1.json"
```

**Parquet内部（2026-09-30），仅购买Parquet源，限定日期、只读：**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-parquet-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-30 --to-date 2026-09-30 --focus-symbols SH601579 SH688535 SH688123 --read-only --out "reports\pq-internal-day5min-volume-20260930-v1.json"
```

后者虽然是单日窗口仍可能读取较多年度RowGroups。失败或慢
应保留实际日志，不能放宽时间窗或自动写源。
仅靠双方来源内部自洽也不足以认证同一物理单位，
还需供应商说明或独立量额口径证据。输出都留在模块内
`H5ParquetReconciler/reports/`；临时计算留在模块内`work/`。

接下来逐步扩展到更多分散的日期（不直接整年分钟全扫），
以判定×100是假说在其它历史日期是否仍成立、残余692
条是否集中在特定代码段和停复牌情景。
千万不要直接复制/合并源K线，也不要把诊断性容差改成放行条件。
