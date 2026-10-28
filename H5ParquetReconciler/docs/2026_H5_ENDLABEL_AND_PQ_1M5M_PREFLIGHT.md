# 2026-10-29：三只沪市高冲突股票H5 1min重聚合证据与Parquet独立周期计划

## 一、用户真实报告已回传（单日、三股）

来源：`h5-1min-vs-h5-pq-5min-20260930-focus3-x100-v1.json`，日期2026-09-30，SH601579、SH688535、SH688123，原生H5一分钟240根、H5五分钟48根、购买Parquet五分钟48根，所有三个H5分钟数据集均存在且无重复键。报告确认为只读、×100实验假设未认证、禁止生产合并。

| 股票日 | H5原生1min结束标记重聚合→H5 5min OHLC/Volume/Amount | 同一H5 1min重聚合→Parquet 5min OHLC全四项 | Parquet 5min成交量原口径 | 乘100后候选成交量 | Parquet 5min成交额 |
| --- | --- | ---: | ---: | ---: | ---: |
| SH601579 | 48/48全部匹配 | 16/48 | 0/48 | 9/48 | 11/48 |
| SH688535 | 48/48全部匹配 | 17/48 | 0/48 | 14/48 | 15/48 |
| SH688123 | 48/48全部匹配 | 20/48 | 0/48 | 15/48 | 18/48 |

在`minute_end_label`下每组48个五分钟窗口完整，而`minute_start_label`每组仅46个完整窗口，09:35与13:05这两组开盘边界缺1分钟；使用该错位候选，三只股票H5内部OHLC全四项均0/46匹配，明确反对把H5一分钟当作开始标签。

各自H5分钟1m→5m Volume对48根均全部匹配；从H5 minute→Parquet五分钟价格/量额大量不匹配，但Parquet vs H5 5min的当日Volume总比为100.0。这是支持跨供应商原始时间分布与量价构造不完全相同的证据，**不能宣称Parquet五分钟必然错误或强制挪移成交量**。H5 1min与H5 5min也可能同上游，非独立交易所级真值。

## 二、后续关键检查必须由Parquet自身1min重聚合出它的5min

仓库已有`tools/validate-parquet-1min-to-5min.py`能够独立读取购买Parquet 1min/5min并测试5种时标候选（含09:30额外开盘记录），输出严格相等、诊断容差内OHLC/Volume/Amount的分字段证据；两个周期均来自相同购买数据供应商。

之前真实重点股票读取5min需要47组RowGroup、候选源行5,685,792，最终仅抽中144根，因此不能直接假定1min scan可接受。原工具此前仅内置30M候选源行的硬拒绝，**缺少可在读取所有OHLCVA之前单独导出的两周期成本报告**。

本轮在既有工具中增加`--plan-only`，只用两个Parquet周期的元数据/RowGroup footer核查日期、源符号统计与候选行/未压缩字节上界：
- 分别输出1min和5min候选RowGroup数、是否通过`--max-candidate-rows`预算、源文件可用性；
- 元数据方案不打开市场OHLCVA列，候选行量是潜在需解码行数上界，不是按证券过滤的实际目标K线条数；
- 真实原路径及候选分组仍仅在源内读取时使用，原始文件无任何写入；
- 不改变正式的开盘特殊记录处理、五种时标规则、数值容差和自动生产准入；
- 新增2项Parquet纯合成回归，原测试总计18项，**Windows还需实际运行**。

## 三、Windows PowerShell命令（仓库根目录，逐条单行）

更新主线：

```powershell
git pull --ff-only origin main
```

运行18项合成测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_validate_parquet_1min_to_5min.py" -v
```

先做**完全不解压/读取行情列的两个周期元数据计划**（30M单周期候选源行上限）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-1min-to-5min.py "D:\stock" --date 2026-09-30 --symbols SH601579 SH688535 SH688123 --max-candidate-rows 30000000 --plan-only --read-only --out "reports\pq-20260930-top3-1min-5min-metadata-plan-v1.json"
```

**仅当上述计划报告显示**`both_periods_source_files_present=true`且`both_periods_within_configured_cap=true`，才执行同三只股票同日的真实、只读核对：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-1min-to-5min.py "D:\stock" --date 2026-09-30 --symbols SH601579 SH688535 SH688123 --max-candidate-rows 30000000 --read-only --out "reports\pq-20260930-top3-1min-to-5min-v1.json"
```

若1min成本超限，只回传plan报告，**不要为了通过强行扩大到100M候选行**；先研究既有完整索引或改造按源分区读取。所有新报告只在`H5ParquetReconciler/reports`，原始数据与scratch不跨出模块；同名报告已存在则换文件名不覆盖。

## 四、判定决策：对来源独立而非真值裁判

1. 若Parquet 1min在`five_start_minute_end_plus_opening_0930`或其它经记录证明的候选规则下可重构Parquet 5min，而H5 1min仅重构H5 5min，就可证明**两套来源在相关周期上各自有内部一致的聚合构造**，不能把五分钟差简单等同于其中一套计算错误；
2. 若Parquet自身1min无法重构其5min，须保留源周期版本/开盘口径/分组冲突，不自动修正；
3. 这只是3只沪市股票、单日证据。为防2026-09-30过拟合，下一步在当前安全范围内选择**2026-08-24的day+5min有界全候选证券重叠核对**并用×100残余分组复查，验证SZ零残余与SH/BJ残余分布是否稳定。绝不直接构建原件覆盖的生产并集。
