# Parquet主库第二阶段：H5缺失日线的独立暂存（2026-10-29）

## 用户实际报告与已经获得的许可

Windows测试 `test_plan_parquet_primary_day_bootstrap_offline.py` **11项全部ok，Ran 11 tests in 0.023s，OK**。

用户实测安全报告：
`parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json`
的源日线窗口为2026-09-01～2026-10-28，扫描complete且键守恒：
- H5唯一日线138,641；购买Parquet唯一日线116,567；交集116,450；
- 两来源重叠日线OHLC在既有价格**0.005元容差**下0条差异；
- 成交量或金额有25,183条差异，**不是六字段严格相同**；
- H5-only 22,191，PQ-only 117，混合日期H5-only为0；H5-only全来自下列**Parquet全日空白**的4天。

| 2026年交易日 | H5-only日线根数 | Parquet该日 | 处理建议 |
| --- | ---: | ---: | --- |
| 10-08 | 5,546 | 0 | 第一个单日暂存/验收 |
| 10-09 | 5,547 | 0 | 10-08成功后独立新批次暂存 |
| 10-12 | 5,549 | 0 | 同上 |
| 10-13 | 5,549 | 0 | 同上 |
| **合计** | **22,191** | **0** | 仅为已有H5日线潜在补齐 |

**重要：** 10-14至10-28在本次H5和购买Parquet日线安全报告中均无记录，因此**这不是最新2026-10-28的全量行情**。不能“补”不存在的行情；后续需检查通达信盘后原始数据是否实际存在、日期是否闭市、质量是否完整，再由未来正式TDX管道补齐。不得因此宣称完成10月全月更新。

## 本轮代码真实交付：只读原件，向模块私有work写隔离Parquet

`tools/stage-h5-only-day-to-parquet.py`是第二阶段的第一个真正**写出转换后的Parquet文件**的工具：
- 输入：H5和购买Parquet所在本机原始路径、一个已生成且与源报告SHA256绑定的**day-only完整gate**、日期、独占的新`work/unified_parquet/staging/<job>`。
- 拒绝混合日、Parquet已有键的日期、缺失H5市场文件、源日期/计数不一致、非法H5 OHLC几何、重复H5股票日、H5/PQ读取异常、来源报告被改动或超`--max-bars`限制。
- 不相信旧报告：每次运行通过仓库已有`reconcile_section`对**本次指定日期重新核对Parquet全部键的精确缺失及H5实际记录数**，源文件大小和mtime在执行前后也要稳定。
- 逐证券仅读取H5原生日线的当天记录，输出`ts`北京零点Unix毫秒、`symbol`购买Parquet格式`600000.XSHG`等、OHLC、volume、amount、source列到独立Parquet；H5候选映射：`open/high/low/close ÷1000`、日成交量`×100`、成交额`×1000`。此映射与老对账器相同，仍属于**待更长期验证的格式候选**，不能冒充供应商单位证明。
- 必须写入新建的、不能覆盖同名目录的私有`work/unified_parquet/staging/<job>/day.parquet`；写后完整Arrow Parquet读回逐字段对比、计算SHA-256并在私有`manifest.json`记录哈希、日期、数量、市场计数、来源安全信息。
- 临时表、回查工作目录`work/stage_day_live_recheck`。**无production promotion、无原始数据写入、无H5镜像生成**；所有源只读，商业行情不会出现在GitHub代码和共享的reports中。
- 如果中途发生异常，未产生完整通过状态的`manifest.json`，该暂存目录应视为**无效批次**，不能交由后续合并器读取。不能直接用H5暂存Parquet文件替换原购买文件，下一轮再开发可回滚版本切换。
- 有界合成集成测试`tests/test_stage_h5_only_day_to_parquet.py`共7项，涵盖H5+Parquet真实结构的小型自造源、完整写出回读、旧报告更改、额外Parquet新键冲突、畸形H5、重键、禁止覆盖。**Windows实机结果尚待执行**。

## Windows单行命令（仓库根目录）

先更新：
```powershell
git pull --ff-only origin main
```

先运行合成测试：
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_stage_h5_only_day_to_parquet.py" -v
```

仅当测试通过，**先对2026-10-08这一天安全暂存**：
```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-h5-only-day-to-parquet.py "D:\stock" --date 2026-10-08 --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --stage-dir "work\unified_parquet\staging\day-20261008-v1" --read-only-sources
```

输出：`H5ParquetReconciler/work/unified_parquet/staging/day-20261008-v1/day.parquet`和同目录私有`manifest.json`，不会触碰`D:\stock`原件。

**仅回传**执行日志及`manifest.json`（其中无任何原始OHLCVA逐行数值）。**不要上传`day.parquet`，它含用户商业/自备真实行情且可能很大**。报告出现“STAGED verified only: 2026-10-08 5546 private bars”只能证明隔离转换和回读成功，不代表最终Parquet正式主库已补齐或已生成H5。

如上一步出错，保留错误日志、不要移动暂存Parquet或手工删除/覆盖源原件。没有成功的manifest的暂存目录不是批准可生产发布的库。

## 下一步开发（不再查分钟机理）

1. 验收2026-10-08单日真实隔离暂存且测试通过；
2. 分别以独立job输出日期2026-10-09（5,547）、10-12（5,549）、10-13（5,549），每个日期都要**重新检验原购买Parquet当天仍无数据**；
3. 开发版本化Parquet主库overlay（采购历史文件作为只读baseline，新日期的隔离分区做私有覆盖层），回归测试幂等、冲突拒绝和原子active指针；
4. 后续按**明确存在的通达信数据**补齐10-14之后，不填造不存在的交易日；再将统一Parquet生成真正Hikyuu可用的day/5min/1min镜像，并同步TDX未来盘后更新；
5. 在日线原生格式完成实际验收之前，不要照搬本轮日线候选成交量倍率到分钟线。
