# 2026-10-27：2026年2月和8月异常来自深市B股；Parquet A股历史主源只读查询API首版

## 一、用户真实key-only报告：2月与8月异常已经缩小到4个深市B股证券日

用户本机执行PR#58的`tools/audit-parquet-month-minute-keys.py`，上传两个安全JSON（仅`ts,symbol`投影，无价量额）：

| 月份 | 扫描股票—日数（所有供应商代码） | 两周期完整241×1min+48×5min | 不完整证券日 | 异常代码和日期 |
|---|---:|---:|---:|---|
| 2026-02 | 77,772 | 77,771 | 1 | 2026-02-24 SZ200706，1min 81，5min 17 |
| 2026-08 | 118,064 | 118,061 | 3 | 2026-08-03 SZ200019、SZ200045、SZ200869，1min各80，5min各16 |
| 合计 | **195,836** | **195,832** | **4** | **均为深市200xxx B股代码** |

用户报告两周期`duplicate_expected_labels=0`、`unexpected_session_labels=0`；四组全部有两周期记录但不满足普通**全日**时间网格；`examples_are_truncated=false`，因此不是“只展示部分异常”。两个报告在`universe=all`（含B股）下完成源时间键检查。四个异常属于代码类别上的深市B股，`core.is_a_share_candidate(SZ200xxx,2026)=false`，因此**没有在这两个月里观察到普通A股候选证券日的分钟时间键异常**，但不等于所有历史证券、日期、成交价量或退市规则都已验证。

**不能直接得出四只B股部分时段数据有错误、是停牌、停牌后复牌，或提供商漏数的结论**：这需要查具体证券停复牌公告/交易日/逐根行情。当前A股主源任务对这四组B股采用**研究隔离**，不静默造K线，不纳入首版A股查询证券范围。报告数据来自用户真实运行而非新增合成单测。

## 二、本轮新增真正可用的本地只读查询

新增`tools/query-parquet-primary-readonly.py`（不转换50GiB历史购买源，不依赖H5）：

- 可由本机Python动态导入后调用`query_bars(root,symbol,period,start,end,max_candidate_rows=...,max_result_bars=...)`，直接返回`bars`列表及独立的`safe_summary`：`bars`是用户在本机有权限使用的原Parquet**OHLCVA真值**，`safe_summary`仅输出计数、源相对路径/文件尺寸/mtime及实际源时间标签范围，不包含任何付费K线数值。
- 支持证券形式`SH600000`、`SZ000001`、`SH688629`等**A股代码模式候选**；本版严格拒绝`SZ200xxx` B股和未经证券主数据确权的类型，BJ 2021上市过渡期谨慎拒绝。**代码模式是保守推断，并非交易所证券主档认证**。
- `--period day|1min|5min --from-date YYYY-MM-DD --to-date YYYY-MM-DD`，查询窗口最多**31自然日**，源行组预算默认**30,000,000**（在读取OHLCVA前预检全部候选rowgroup），返回值默认最多**25,000根**，超过报错而不是静默截断。按Footer时间、Symbol统计保守剪枝；源H5及TDX均不会访问，不能自动补源缺口。
- 价格/量额来自原供应商值，不调整量纲、金额，不进行复权/反复权，不改动购买源；遇到请求证券原时标重复、OHLC非法、负量额/非有限值立即拒绝，避免误用不可信数据。
- **保留原始源时间戳及北京时间**。day原源经已有Footer报告显示多为08:00，统一`normalized_query_label=YYYY-MM-DD`但保留`source_beijing_time`；1min保留已验证的**结束标签**并保留独立09:30开盘记录；5min保留**开始标签**，不擅自+5分钟改为H5的结束标签。
- 每根本机返回记录含`source_file_relative_path`与`source_row_group`，安全汇总`source_file_stat_provenance`保存源文件相对路径、长度和mtime（**不是内容SHA256，也不是完整交易所来源认证**）。
- 命令行默认只在`H5ParquetReconciler/reports/`生成新`safe_summary`JSON，拒绝覆盖同名文件，**不包含付费价量额原值**。`--show-first-bars 3`可显式在**本机终端**打印最多10根原始OHLCVA用于人工核对，不要把这些打印到GitHub/公开Issue。正式业务可在本地Python直接使用`query_bars`返回值构建K线和模型输入，但自动交易使用前还需复权/证券主档/停牌规则等更全面质量门槛。
- 新增`tests/test_query_parquet_primary_readonly.py`9项使用无版权临时Arrow Parquet测试，覆盖day08:00/1min09:30/5min09:30原时标、多周期、候选读取预算、重复键、不存在证券、异常OHLC、B股拒绝、结果上限及安全报告不写市场数据。此批测试/本机实际查询**尚待Windows运行**；此前PR#58的8项测试通过情况也尚未收到单独完整报告。

## 三、Windows一次性验收

在仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --max-result-bars 25000 --read-only --out "reports\pq-primary-query-SH600000-5min-2026-09-30.json"
```

该命令只会保存**安全元信息报告**，期望查到SH600000的48根五分钟数据（此前9月30日真实日线分钟报告已经观察到相同样本，仍应以本机新工具回传的`matching_bar_count`为准）。

如希望在自己的**本机终端**查看前3根原始K线，可以另用**全新**`--out`文件名加`--show-first-bars 3`。不要公开转存购买的数据源价量额。

上一轮PR#58预计258项测试，本轮新增9项，预计**267项**（实际数量和全部通过情况需Windows日志）；新工具未对用户真实购买源运行，不能声明已生产验收。验证后可将`query_bars`作为未来Parquet主源查询基础，继续开发**按证券+日期的实际完整性查询**、标准化时段解释及通达信盘后**独立、可回滚**新增数据层。

## 四、下一阶段待解决事项

Parquet主历史源文件级数据目前已覆盖2011-01-04至2026-09-30；2026年2/8月已见四组B股特殊证券日，但**不能直接认定2011—2026全历史每只A股完整或交易所逐笔正确**。只读查询首版应先在真实SH600000或SZ000001的2026-09-30执行，再抽2011、2016、2022少数实际存在的股票日；确保没有将复权、除权与量纲混为一谈。后续叠加TDX新日完整日期，不重写/覆盖50GiB购买Parquet和H5原数据包。
