# 2026-10-28：10组241→240真实候选预演跨来源证据门槛

## 已完成的真实数据验收

用户Windows实际运行的8项合成测试均通过：Ran 8 tests in 0.217s, OK。
用户回传新增9份真实候选预演安全JSON；加此前SH600000/2026-09-30
已回传的1份，共10个股票日，4个股票，4个日期，涉及两个不同月份。
逐项核对10份预演：四道六字段门槛（首根1/1、余239/239、全240/240、
候选聚合5分钟48/48）全部10/10通过；原始241分钟记录每条参与
一次候选构建，未丢弃或补造；生产自动写入一律为false。
10组全240根价格字段最大相对误差5.08e-08，volume最大相对误差
0，amount最大相对误差1.07e-08；这表示诊断容差内匹配，
不等于全部市场数据位级一致、也不等于已认证全历史映射。

## 只读证据汇总工具

tools/summarize-tdx-parquet-normalization-previews-readonly.py

该脚本读取1..12份既存 H5ParquetReconciler/reports/*.json 
安全预演报告，不读取TDX、Parquet或H5原始K线。对每份报告
强制核对股票日标签、完整来源SHA256、Parquet 1min/5min
stat-only清单指纹、241→240行来源贡献、四道六字段
指标与gates是否矛盾、非有限误差、安全标志、重复样本。

建议指定--cohort，输入此前已有的
reports/tdx-pq-opening-cohort-ten-stockdays.json。
脚本会逐股票、逐日期要求预演报告和历史开盘审计报告
集合一致，TDX完整文件SHA及Parquet stat-only清单
指纹一致，原始开盘诊断结论和候选预演结论一致；
任何来源版本或交易日冲突立即拒绝并报错。
该校验只证明两份独立生成的SAFE报告中记录的
来源指纹相同，并不能将stat-only变成真正的文件内容认证。

安全JSON输出仅含样本代码、日期、输入报告SHA、
TDX内容SHA、Parquet stat-only指纹、四门匹配布尔值、
全240根的六字段最大相对误差、总数和研究性结论。
不导出任何单根成交量、价格、分钟标签、绝对私有路径。
原始数据、生产指针、overlay与私有缓存保持不变。

## Windows单行PowerShell验收

在 D:\ChatGPT\AStockDataTools 仓库根目录执行：

git pull --ff-only origin main

先运行新增8项**纯合成**测试（这8项目前尚待Windows验收）：

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_summarize_tdx_parquet_normalization_previews_readonly.py" -v

然后将10份预演报告和此前审计汇总进行交叉验收（单行，易复制）：

```powershell
$names=@("sh600000-20260928","sh600000-20260929","sh600000-20260930","sz000001-20260928","sz000001-20260929","sz000001-20260930","sh600519-20260817","sh600519-20260930","sz300750-20260817","sz300750-20260930"); $argsList=@(); foreach($n in $names){$argsList+=@("--report","reports\tdx-pq-$n-normalization-preview-v1.json")}; & ".\.venv\Scripts\python.exe" "H5ParquetReconciler\tools\summarize-tdx-parquet-normalization-previews-readonly.py" @argsList --cohort "reports\tdx-pq-opening-cohort-ten-stockdays.json" --read-only --out "reports\tdx-pq-normalization-preview-cohort-ten-stockdays-v1.json"
```

预期如下，**需用户本机真实运行后才能记为已验收**：

Preview samples: 10 verdict: exploratory_preview_target_met_not_certified

这是探索证据满足门槛，永不授权自动生产转换。
若结果文件已存在，必须使用新的目标文件名，程序拒绝覆盖。

## 下一步

在更多时间跨度、停复牌及异常交易日验证不变式和拒绝条件，
再为映射规则定义显式版本号和可审计的来源引用。
只有获得明确授权后才能研究隔离私人暂存与回滚；
本轮仍不输出、持久化或接入任何240根候选K线。
