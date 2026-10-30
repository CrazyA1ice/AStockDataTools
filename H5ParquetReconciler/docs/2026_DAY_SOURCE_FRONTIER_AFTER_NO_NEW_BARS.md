# 2026-10-30：购买Parquet和原H5在10月14～29日均无新日线——先确定数据源实际更新边界

## 已验收事实与止损决策

Windows `test_audit_post_snapshot_h5_stockdays_readonly.py` **14/14 OK（18.930秒）**。对已登记私有逻辑版本的3只股票（SH600000、SZ000001、SH600519）在2026年10月14～29日进行真实H5原生日线和购买Parquet独立只读核查，脱敏SAFE `reports/post-snapshot-h5-stockdays-4bfc07dc7afc.json`证明：

- `observed_h5_stock_days=0`；`observed_purchased_stock_days=0`；`selected_stockdays_h5_only_candidate=0`。
- `selected_stockdays_neither_source=48`：**16个日历日 × 3只股票=48个股票日历日组合**，不等于48个交易日、更不等于全市场休市。
- H5选中SH/SZ的原市场源文件2个、2026购买day文件9个（仅stat fingerprint，**不是文件内容SHA**）。均未被修改，私有活动指针、正式行情路由均未变化。
- `whole_market_date_purchased_absence_certified=false`、`whole_market_h5_date_completeness_certified=false`，没有任何新日期获得H5补缺许可证。PR #165已合并main（`fbb32eb`）。

**所以不应继续对10/14以后生成空分区或反复开展整日补缺审核，也不应根据旧4日资格自动补H5。** 需要先回答：真实原H5股票日线最后记录在哪天、购买Parquet/2026文件的全股票时间戳范围上界在哪天？是否源文件本身未更新、现有数据目录不对、或供应商更新另有落点？

## 新增只读工具：`inspect-day-source-freshness-frontier-readonly.py`

1. 对1～10只明确选择的A股、单个年份（首轮2026），读取`D:\\stock\\HikyuuData/{sh,sz}_day.h5`中各股票复合日线表的**最后8个日期键（不足8条读取全部）**。先验证日线字段集合/整数位宽，再验证这8个键能转换为合法YYYYMMDD0000日期、严格升序。返回每只股票**最后一个物理存储位置的日期**、该表行数，以及所选股票观察到的最大尾部日期。只检查尾部升序，**不能认证整个H5历史完全有序**；也不是原生Hikyuu C++驱动可用性认证。
2. 对现有购买`D:\\stock\\AllCycleAStockData\\day`下匹配2026的Parquet文件，只检查每个row group的元数据footer `ts.min/ts.max`，计算**所有股票总体**的时间戳候选上下界。不会扫描任何真实购买OHLCVA行。若有未提供统计值的row group，单独计数。无论页脚统计是否完整，始终设置`latest_source_date_certified=false`，仅以`all_nonempty_rowgroups_have_ts_minmax`说明行组上下界是否完整；不能凭文件名及元数据推定供应商确切最新交易日期。
3. **严格区分对象：** 原H5尾部是指定股票真实记录位置的日期；购买Parquet上界是所有股票RowGroup的**全局统计区间**，并非SH600000/SZ000001/SH600519任一股票的已证最新交易日。两者不能当成同等精度的交易所日历证明；尤其Parquet footer只代表当前命名年份文件内的统计范围，而不是供应商所有存储位置。
4. 检查原始H5及购买Parquet文件大小/mtime前后稳定，摘要仅做文件stat元数据指纹，不是数据内容哈希。最多128个购买文件和20,000个rowgroup元数据，最多10只H5股票，每只只读8个尾部键；超限拒绝。只读原文件、不访问任何private/production指针，不改变原H5或购买Parquet，无自动数据填充、不生成空日线。
5. 只在模块`reports/`生成新脱敏JSON，按请求顺序用slot 1..N标识股票，**不输出真实股票代码、原始整数OHLCVA、付费价格/成交量、市场数据的绝对路径**。真实原H5数据会被打开以读取尾部键，但不会写入或修改；只打开购买Parquet元数据，不读取付费行情列。
6. 若源记录确实停在10/13或更早，**下一轮直接调查外部下载/通达信盘后转换/购买数据文件更新的实际落点及配置**，不要再优化当前无新行的统一Parquet引擎；若购买Parquet全局上界晚于H5尾部，则再针对**确切年份/新月份和选定股票**用现有购买day有界查询验证是否有真实新数据，并检查月文件命名/目录等来源选择问题。

**测试：** 新增14项全合成HDF5/PyArrow回归（真实临时H5和Parquet，存于模块`work/`），涵盖最后日期/rowgroup footer、两者时间范围不一致、重复H5日键、无效日期、H5结构损坏、Parquet缺ts列/缺footer统计、检查期间文件状态变化、缺文件/股票、越界、SAFE不可覆盖/脱敏等。尚未在用户Windows运行，PR保持Draft。

## Windows单行验收

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/day-source-frontier-freshness-inspector-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/day-source-frontier-freshness-inspector-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_inspect_day_source_freshness_frontier_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "14项日期边界合成测试失败，停止真实数据检查" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-day-source-frontier-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-day-source-freshness-frontier-readonly.py --source-root "D:\stock" --symbols SH600000 SZ000001 SH600519 --year 2026 --out $out --read-only-source-frontier; if ($LASTEXITCODE -ne 0) { throw "原H5/PQ日线最新记录边界检查失败" }; Write-Host "脱敏SAFE：$out"
```

合成测试没通过则PowerShell自动中止；通过后才能读真实原H5尾部键和购买Parquet页脚。仅回传终端摘要与新脱敏SAFE JSON，不上传包含版权行情的H5/Parquet原始文件。

## 后续业务开发原则

若确定本机源数据过期，应优先修复/连接**真实**数据采集/文件落点，不允许对不存在的交易日期生成占位K线，也不能把H5候选金额单位未认证的数据写入真实生产Hikyuu。若确认第三方购买2026文件尚未更新而通达信盘后数据更近，才另立受审计的只读通达信原始解析、和购买数据重叠校验，然后考虑只在模块私有Parquet中增量追加。正式H5镜像、隐式fallback及生产路由仍关闭。
