# 2026-10-28：每股票日三份SAFE证据交叉核对与字段级保守准入判定

## 研究进展与未解决的问题

用户Windows实机运行 `test_triage_tdx_parquet_isolated_high_readonly.py`：
`Ran 9 tests in 0.303s — OK`。回传的两份真实
`isolated-high-mechanism-v1.json` 一致表明，
SH600000/2026-07-16及SH600519/2026-06-30各只有一根1min High
不匹配；该分钟在TDX和Parquet各自5min区间内均不是最大High，
两来源5min全部六字段48/48在诊断容差内一致。
这是**不影响5min最高价的孤立一分钟High冲突**，
不是一分钟源数据逐根相等，也不代表可以改动或丢弃异常分钟。

另外已有 `audit-tdx-vs-parquet-day5min-readonly.py` 真实报告证明，
SH600519/2026-06-30还存在日线Volume独立冲突：
TDX day vs Parquet day Volume 0/1（最大相对误差1.99456e-05）；
Parquet 5m汇总 vs Parquet day Volume 0/1（2.52474e-05）。
SH600000/2026-07-16的对应两项日线Volume均1/1通过。
需要严格区分分钟High冲突和日线Volume冲突。

## 新增证据仲裁工具——不读取市场行情

`tools/evaluate-tdx-parquet-case-evidence-readonly.py`

必须为**同一只股票同一天**提供三个现有SAFE JSON：

- `--preview`：241→240候选对TDX 240根的四门六字段详细诊断；
- `--mechanism`：一分钟High异常与TDX/Parquet五分钟峰值机制诊断；
- `--crosscycle`：TDX 1min/5min/day和Parquet 5min/day跨周期对照。

工具会拒绝跨股票/日期、格式不明、来源SHA不一致、
1min/5min/day的Parquet stat-only清单指纹不一致、
四门六字段匹配数量冲突、相互矛盾的安全标志和判定、
不在模块reports目录内的输入、重复JSON键或非有限数值。
始终保留两个独立结论：

- **分钟级**：`isolated_high_not_five_minute_max_minute_disagreement_remains`
  表示该分钟High在五分钟区间不控制最高价，但一分钟仍为不一致；
- **日线成交量**：TDX day vs Parquet day与Parquet 5min vs day
  分别输出`diagnostic_match`或`mismatch`，不互相掩盖。

输出仅包含原SAFE报告SHA、TDX各周期全源SHA、Parquet
stat-only指纹、字段不匹配计数、只读判定和安全禁令；
不会读取TDX/Parquet/H5市场文件，不导出行情和具体分钟。
无论如何 `production_mapping_certified=false` 和
`eligible_for_automatic_production_union=false`。
报表来源本身并未由第三方加密认证，Parquet清单不是内容SHA，
严格限制为可审计诊断而非权威来源裁判。

## 已实施验证与待验收

开发容器中已运行11项合成测试：**11/11 OK**；
并将真实用户上传的两组各三份SAFE JSON放在隔离目录中运行，
结果与此前独立人工核验一致：

| 股票日 | 分钟判定 | TDX day vs PQ day Volume | PQ 5min sum vs PQ day Volume |
| --- | --- | --- | --- |
| SH600000 / 2026-07-16 | 单High孤立不一致，不能材料化 | 匹配 | 匹配 |
| SH600519 / 2026-06-30 | 单High孤立不一致，不能材料化 | **不匹配** | **不匹配** |

下面是Windows单行PowerShell命令，需本机验收；
输入JSON必须已经存在于`H5ParquetReconciler/reports/`。

```powershell
git pull --ff-only origin main
```

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_evaluate_tdx_parquet_case_evidence_readonly.py" -v
```

浦发银行（单行）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\evaluate-tdx-parquet-case-evidence-readonly.py --preview "reports\tdx-pq-sh600000-20260716-boundary-detail-v1.json" --mechanism "reports\tdx-pq-sh600000-20260716-isolated-high-mechanism-v1.json" --crosscycle "reports\tdx-pq-sh600000-20260716-high-crosscycle-v1.json" --read-only --out "reports\tdx-pq-sh600000-20260716-field-disposition-v1.json"
```

贵州茅台（单行）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\evaluate-tdx-parquet-case-evidence-readonly.py --preview "reports\tdx-pq-sh600519-20260630-boundary-detail-v1.json" --mechanism "reports\tdx-pq-sh600519-20260630-isolated-high-mechanism-v1.json" --crosscycle "reports\tdx-pq-sh600519-20260630-high-crosscycle-v1.json" --read-only --out "reports\tdx-pq-sh600519-20260630-field-disposition-v1.json"
```

输出文件名必须尚不存在；禁止删除、覆盖或覆盖旧验证记录。
若有新的来源版本变动，拒绝跨版混合，而不是重用旧判定。

## 主线后续

两组孤立High机制已确认，不继续重复构建同类工具。
对贵州茅台日线Volume差异，只将其保持为独立冲突，
未来以真实来源修订/口径证据进一步判断，不能自动更正。
标准化准入仍仅有实验规则ID，生产转换、H5/Parquet并集与
原件改写均在显式授权、覆盖研究和回滚验证之前保持关闭。
下一阶段应回到H5/Parquet的重叠覆盖与实际差集主线，
以此字段级安全合同支持后续明确的来源选择策略。
