# 2026-10-28：H5/Parquet 2026-09-30 日线↔五分钟成交量内部守恒与残余分时验证

## 实际上传：两来源各自day↔5min安全报告（不是合成数据）

已收到：
- `h5-internal-day5min-volume-20260930-v1.json`
- `pq-internal-day5min-volume-20260930-v1.json`

两个报告均为`scan_complete=true`，日期窗口仅`2026-09-30`，
证券范围`a-share-candidate`仍仅代码前缀筛选，未做证券类型认证。
均只读且`safe_to_automatically_union=false`。

| 实证指标 | H5 | 购买Parquet |
| --- | ---: | ---: |
| 完整48根五分钟线且当天有日线的证券日 | 5,550 | 5,560 |
| day与5min按来源原始字段单位同倍率比较，0.1%容差内匹配 | 5,550 | 5,556 |
| day与5min原始字段严格完全相等 | 5,497 | 未输出该口径 |
| 0.1%容差外 | 0 | 4 |
| 有48根五分钟但当天没有日线 | 0 | 11 |

**H5口径细节不可误读**：来源H5审计定义`candidate_day_target`
为`H5 day transCount × 100`，并分别检验原始五分钟汇总与其
×100倍汇总。H5真实结果`baseline_day_minute_volume_agree_0_1pct=0`、
`candidate_day_minute_volume_agree_0_1pct=5550`、
`h5_raw_daily_equals_sum_minute_raw_exact=5497`。
因此可陈述H5 day与5min在**同倍率的原始transCount数值上**
于0.1%容差内完全自洽；不能把`baseline=0`描述成数据缺失
或内部量额普遍不守恒。这强化但不能认证跨供应商的×100假设。

Parquet day与5min同倍率守恒：5560组中5556组通过，
4组不一致均为BJ前缀：
`BJ920050`、`BJ920110`、`BJ920121`、`BJ920160`。
另有11组Parquet只有48条完整5min、没有对应day：
`SH600293`、`SH601059`、`SH601198`、`SH603183`、
`SH688496`、`SZ000016`、`SZ002667`、`SZ002731`、
`SZ002813`、`SZ002860`、`SZ300082`。
不能简单将这11组归为停牌、上市证券、供应商错误或H5缺口，
需要与主覆盖报告的21组PQ-only股票日逐一比对后才能归属。

## 独立证据：全天匹配仍存在五分钟残余分布差

Parquet审计额外针对先前残余冲突前三只沪市股票做四周期聚合核对：

| 证券 | 各自day↔5min守恒 | 候选跨来源日线总量 | H5×100后5min仍冲突（原容差） |
| --- | --- | --- | ---: |
| SH601579 | 通过 | 通过 | 39/48 |
| SH688535 | 通过 | 通过 | 34/48 |
| SH688123 | 通过 | 通过 | 33/48 |

这里的day近似守恒只证明交易日总量差很小；多根五分钟
差异提示**区间内的量分布**仍不同，但还不能推出
“逐分钟发生了重新分配”或判定哪一来源更准确。
需要进一步比较上午/下午累计差、差值抵消比例、相邻区间
差异符号与价格OHLC构造，以区分时间边界、历史修订、
大小单处理、不同供应商聚合等候选解释。

## 下一步复用现有 focused x100 session 工具（针对性修复）

现有`tools/analyze-5min-x100-focused-sessions.py`已能从
`exact_residual_top_stock_days`自动选择冲突最多的3只股票，
只在内存中归一化H5五分钟量×100并比对各自上午/下午
净差、毛差、抵消比例、相邻差异符号、五分钟OHLC分布，
输出不包含OHLCVA原始条。但其旧`load_baseline`仅允许
`requested_periods=['5min']`，无法接收用户已经验收的
`requested_periods=['day','5min']`完整双周期JSON。

本轮仅调整此输入检查：两种形式均可接受；对双周期
必须同时满足同一年、同一日期、候选证券范围、
day分区扫描成功、无issues、不能自动并集，
多分区或跨窗口错误继续拒绝；新增3项合成回归，
总计8项，**尚待Windows运行**。

### Windows PowerShell（仓库根目录，所有命令单行）

```powershell
git pull --ff-only origin main
```

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_analyze_5min_x100_focused_sessions.py" -v
```

**先仅用Parquet footer元数据估算将读取的RowGroups，不读行情数值：**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-x100-focused-sessions.py "D:\stock" --date 2026-09-30 --baseline-report "H5ParquetReconciler\reports\h5-pq-overlap-20260930-day5min-v1.json" --top-symbols 3 --plan-only --read-only --out "reports\h5-pq-20260930-x100-focused-read-plan-v1.json"
```

元数据方案显示可控后，**仅针对来源有完整48根且存在
残余冲突的3只股票真实只读核验分时差异**：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-x100-focused-sessions.py "D:\stock" --date 2026-09-30 --baseline-report "H5ParquetReconciler\reports\h5-pq-overlap-20260930-day5min-v1.json" --top-symbols 3 --read-only --out "reports\h5-pq-20260930-x100-focused-sessions-v1.json"
```

文件必须使用尚不存在的新名字；所有生成报告只在
`H5ParquetReconciler/reports/`，不得输出到源`D:\stock`；
Parquet读取采用已实现的元数据剪枝，不承诺特定耗时。
若来源在两次报告间改变，原精确掩码不匹配时工具应
拒绝继续认定旧证据成立；不得用放大容差或重写源K线
人为使之匹配。

## 主线后续

在三只股票分时分布证据到手后，转向**另一个历史交易日的
有界day+5min全市场核对**，对2026-09-30发现的
“深市候选无残余，沪市/北交所残余集中”和×100假说
做跨日期复现，不把一日经验作为正式供数规则。
同时保留Parquet四个BJ日线不守恒与11个仅有5min的
股票日作为独立问题。所有来源修改、自动回填、正式并集
仍须另行明确授权和独立认证。
