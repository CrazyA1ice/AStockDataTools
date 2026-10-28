# 2026-10-28：TDX vs 购买Parquet 一分钟开盘归并——10组真实股票日实证

## 输入证据与范围

10个**相互独立的股票-日期组合**，全部由用户本机严格只读
`audit-tdx-vs-parquet-1min-opening-readonly.py`生成的安全JSON核对。
其中前6组已经在
`tdx-pq-opening-cohort-six-stockdays.json`中汇总；
新增后4组来自用户2026-10-28上传的安全报告。

| 股票 | 2026-08-17 | 2026-09-28 | 2026-09-29 | 2026-09-30 |
| --- | --- | --- | --- | --- |
| SH600000 浦发银行 | 未验 | 通过 | 通过 | 通过 |
| SZ000001 平安银行 | 未验 | 通过 | 通过 | 通过 |
| SH600519 贵州茅台 | 通过 | 未验 | 未验 | 通过 |
| SZ300750 宁德时代 | 通过 | 未验 | 未验 | 通过 |

- 合计**4只股票、4个日期、2个月份、3类行业、10个股票日**；
  其中银行样本较多，不可误称为覆盖全行业、全股票或全历史。
- 每个实际股票日：TDX源`.lc1` **240根END标记**、
  购买Parquet`1min` **241根**（单独09:30+240 END标记），
  Parquet`5min` **48根START标记**。
- 在这10组中，将Parquet **09:30和09:31完整聚合成END=09:31**
  （open第一条、high最大、low最小、close最后一条、
  volume/amount求和），其余239根END分钟保持原时间键，
  与TDX 240根的**所有六字段均在设定诊断容差内匹配**；
  Parquet原241条数据按包含09:30聚合到48根5min六字段亦全部匹配。
  成交量、成交额差异一般为零或接近零，不能由此推出价格
  二进制逐位一致。
- 当前10份报告验证的是历史库存的部分日期/部分股票。
  **未覆盖停牌复牌、集合竞价字段定义、复权前后、除权日、
  深沪其他板块的发行上市边界或不同采集版本。**

## 最新四组新增真实证据（和已知六组分离）

1. `tdx-vs-pq-sh600519-20260817-minute.json`
   首根直接比时open/high、volume/amount不吻合；
   合并后六字段通过，剩余239根逐根通过。
2. `tdx-vs-pq-sh600519-20260930-minute.json`
   首根直接比时open、volume/amount不吻合；
   合并后六字段通过，剩余239根逐根通过。
3. `tdx-vs-pq-sz300750-20260817-minute.json`
   首根直接比时价格字段可全部吻合，但volume/amount不吻合；
   合并后六字段通过，剩余239根逐根通过。特别警示：
   不能用开盘价格是否相同来决定忽略09:30。
4. `tdx-vs-pq-sz300750-20260930-minute.json`
   首根直接比时open/high、volume/amount不吻合；
   合并后六字段通过，剩余239根逐根通过。
   首根未经归并的成交量相对差异约0.3507879302，量额
   缺失不能视为零成交占位。

上述四份报告的`first_minute_opening_merge_hypothesis`：
`first_minute_all_six_fields_match_after_merge=true`、
`remaining_239_all_six_fields_match=true`、
`all_240_all_six_fields_match_after_merge=true`；
`parquet_opening_241_in_first_five_minute_vs_five_minute`六字段
分别48/48在容差内匹配。

TDX全文件SHA256已出现在原生probe报告；Parquet只有文件
大小和mtime的**stat-only**清单指纹，不是全量内容认证。
全链路始终`eligible_for_automatic_production_union=false`。

## Windows：只读汇总10组原始安全JSON（单行PowerShell）

于仓库根目录执行。要求下列10份报告均已存在本机
`H5ParquetReconciler/reports`。没有任何行情读取或价格写入。

```powershell
$names=@("tdx-vs-pq-sh600000-20260928-minute.json","tdx-vs-pq-sh600000-20260929-minute.json","tdx-vs-pq-sh600000-20260930-first-minute-merge-v2.json","tdx-vs-pq-sz000001-20260928-minute.json","tdx-vs-pq-sz000001-20260929-minute.json","tdx-vs-pq-sz000001-20260930-minute.json","tdx-vs-pq-sh600519-20260817-minute.json","tdx-vs-pq-sh600519-20260930-minute.json","tdx-vs-pq-sz300750-20260817-minute.json","tdx-vs-pq-sz300750-20260930-minute.json"); $reports=@(); foreach($n in $names){$reports+=@("--report","reports\$n")}; & ".\.venv\Scripts\python.exe" "H5ParquetReconciler\tools\summarize-tdx-parquet-minute-evidence-readonly.py" @reports --read-only --out "reports\tdx-pq-opening-cohort-ten-stockdays.json"
```

如果`reports/tdx-pq-opening-cohort-ten-stockdays.json`已存在，
必须换一个**新文件名**，不能覆盖原报告。期待的概况（还需
实际在Windows运行后才可视为已验证）：

```text
Evidence samples: 10
verdict: exploratory_sample_target_met_not_certified
```

此项只表示满足探索样本数量门槛且没有发现当前样本的差异；
**不是生产转换认证**。

## 下一阶段重点：只读候选标准化预演，而不是直接并集

- 明确`raw_241_opening_plus_end`与
  `candidate_tdx_240_end`为两个不同视图，不覆盖原始行。
- 若做内存候选视图，只允许明确09:30+09:31合并为09:31，
  其余239根原样对齐；六个OHLCVA字段、来源时间/哈希和
  可追溯的原始记录位置保持不丢失。
- 对于缺失、重复、日历异常、非零成交的特殊开盘场景，
  应拒绝自动转换，输出安全异常类别；不应凭数字相似
  随意改口径。
- 尽快增加过去其它月份/年份、非完整分钟、停牌复牌、
  特别交易与复权风险样本，优先寻找反例。
- 在原始TDX、购买Parquet、H5全部保持不变且检验通过的
  前提下，再开展**隔离版本化私有暂存、人工批准与回滚演练**。
  当前不修改源数据、不启用生产自动并集，也不上传付费行情。

