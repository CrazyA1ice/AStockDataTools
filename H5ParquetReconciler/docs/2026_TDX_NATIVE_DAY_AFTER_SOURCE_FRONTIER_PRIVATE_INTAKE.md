# 2026-10-30：两套日线源落后后，复用本机通达信原生.day作为独立盘后候选

## 真实Windows已确认的数据状态

`test_inspect_day_source_freshness_frontier_readonly.py` **14/14 OK（6.988秒）**。用户SAFE `reports/private-day-source-frontier-c1fee86b0cc1.json` 已验证：

- 所选3只股票SH600000/SZ000001/SH600519的原H5最后物理日线均为**2026-10-13**。
- 购买`AllCycleAStockData/day`的2026年9个文件/17个行组（17个都有ts页脚上下界），全股票行组时间戳最新候选上界**2026-09-30**，不是指定股票真实最新日线或供应商最后更新时刻。
- 2026-10-14～29的所选股票，原H5、购买Parquet都经原生实测返回**0条**；不能虚构历史交易数据/依赖原H5补缺。
- 原行情均未修改，私有活动版本指针与生产数据路由没有被读/写。PR #166已合并main（`2b1ab65`）。

## 为什么现在转向通达信

仓库`docs/2026_TDX_NATIVE_READONLY_PROBE_V1.md`已经记载用户本机通达信原生日线文件`D:\software\TDX\vipdoc\sh\lday\sh600000.day`的先前只读分析；仓库既有`tools/probe-tdx-native-readonly.py`支持读完整原生日线32字节记录、股票和来源日期/全文件SHA256；`tools/tdx-postclose-private-overlay.py`已有规范化单股票日JSON的私有校验/显式暂存独立能力，但此前**缺少原生 .day 到其JSON契约之间的直接安全适配**。

这次新工具`tools/intake-tdx-native-day-to-private-postclose-json.py`专门完成这一缺口：

1. 支持**一个**指定通达信原生 `.day` 路径、一只规范股票、一天完整日期和`--strictly-after`父版本截止日期（当前`2026-10-13`）。不会猜测最新交易日、不会直接合并指定日期之前的旧数据，也不解析分钟线。
2. 复用既有`NATIVE.inspect()`对**完整**32字节源全文件逐记录验证日键严格单调、价格OHLC结构、候选金额/量合法、原源SHA256和文件未变化。随后独立只读定位所选原始记录，核验完整文件SHA及源stat仍吻合；若指定日期没有真实记录，生成`native_tdx_stockday_not_present` SAFE，明确`source_last_date`，**不生成空私有JSON或虚构日线**。
3. 默认无任何真实行情副本，仅在模块`reports/`新建脱敏SAFE，记录源真实首/尾日期、选择日期是否存在、源内容SHA、是否已有可处理候选。不会在SAFE输出真实股票代码/价量额、通达信绝对目录、历史K线或源整数。
4. 当确有该日期真实记录且用户**显式**同时给出`--private-dir`和`--allow-private-normalized-copy`时，才从原生32字节候选转成旧接口已验证的`AStockDataTools normalized local postclose stock-day v1`格式，精确1条日线，存于Git忽略的模块`work/tdx_postclose_native_intake/intake_<hex>/normalized-day.json`，然后用旧`POSTCLOSE.validate()`及JSON读回校验原值，生成仅SHA/统计的SAFE。这个文件可以由用户在**单独显式批准**后调用已有`tdx-postclose-private-overlay.py`进一步校验/暂存；本工具**从不调用暂存/启用/回滚**。
5. 价格按TDX .day标准候选的价格整数÷100，原生volume/amount原值保留；**物理单位/交易所行情真实性、复权/分钟一致性均未独立认证**，因此输出状态始终`ready_for_automatic_parquet_h5_union=false`。尤其不能自动写到购买Parquet/生产H5或覆盖之前SHA登记的15条日线。
6. 新工具有**11项全合成测试**，使用临时32字节原生通达信`.day`样本，测试默认只读、显式真实私有JSON+旧接口契约、无最新日期拒绝、重复/倒序日键、源改变、边界日期/路径错、保护已有SAFE与私有目录、量额仍未认证。真实本机执行前PR保持Draft。

## 本轮Windows单行试点：先查实际通达信尾日、**不复制**行情

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/tdx-native-day-private-intake-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/tdx-native-day-private-intake-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_intake_tdx_native_day_to_private_postclose_json.py" -v; if ($LASTEXITCODE -ne 0) { throw "11项合成测试失败，不读真实通达信" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\tdx-native-day-intake-readonly-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\intake-tdx-native-day-to-private-postclose-json.py --source "D:\software\TDX\vipdoc\sh\lday\sh600000.day" --symbol SH600000 --date 2026-10-29 --strictly-after 2026-10-13 --out $out --read-only-original-tdx; if ($LASTEXITCODE -ne 0) { throw "原生通达信10月29日只读核查失败" }; Write-Host "脱敏SAFE报告：$out"
```

**若实际旧日线文件只到10月13日**，结果应为`native_tdx_stockday_not_present`，SAFE有真实`source_last_date`。此时不要伪造10/29分区，而应该检查通达信客户端盘后下载/扩展市场/多实例数据位置或是否有另外的最近更新`.day`文件。

**若文件已包含10/29单股日线**，结果为`native_tdx_stockday_available_not_staged`，下一轮可选择显式私有拷贝，并与Parquet优先规则及H5候选口径做额外审核；不能仅凭该单只股票日成功就宣布正式数据主库/全市场更新已经完成。

只回传11项测试输出及脱敏SAFE JSON，不上传通达信原始二进制`.day`、付费Parquet/原H5或任何带OHLCVA的normalized-day.json。真实通达信源尾日尚未完成最新Windows实测，下一轮需据实决定是否对其他股票或当前日期重复核对。
