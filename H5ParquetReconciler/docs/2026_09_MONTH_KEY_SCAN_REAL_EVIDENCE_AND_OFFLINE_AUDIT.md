# 2026-10-28：整月3股共享键扫描实证；离线严格审计完整性和单日定位一致性

## 用户本机真实安全JSON（不是估计）

报告`pq-202609-three-symbol-month-shared-5min-keys.json`：
- 日期2026-09-01～30，**3股×30个自然日=90个证券日组合**。
- SH600000、SZ000001、SZ300750每股均**21个有记录日×48个5min源键=1,008键**，
  合计**63个有记录股票日、3,024个真实源键**。
- 三股票剩余**9个共同零键日**：09-05、06、12、13、19、20、25、26、27。
  其中**09-25是工作日形式的零键日**，需独立交易日历核对；报告不能
  判定它是行情缺失还是正常休市，绝不自动补K线。
- 9月30日三股精确非空组分别**18/19/17**，每个组号和键数与之前的
  `pq-20260930-three-symbol-shared-5min-keys.json`逐项完全相符。
- 按**整个9月**去重后，三股中的**每一股都占用了47/47个RowGroup**，
  因此月度全窗口查询无法靠“仅扫描本股非空RowGroup”剪掉源组；
  **定位的价值主要在逐日/小窗口查询**。
- Footer并集47组、5,685,792源键行完整扫描一次；每股保守单独Footer
  上限5,685,792行，三股独立合计17,057,376行。理论避免重复源键行
  11,371,584，约66.7%；**不是实际磁盘字节/CPU时间减少66.7%**。
- 本次键列扫描**2.357598s**，含Footer/stat的完整规划**3.900790s**。
  之前三股**单日**试点总3.113772s、键列2.104793s；两实验跨运行
  无反序控制，不能据此声称整月查询有确定的净加速倍数。
- 来源9文件的stat-only清单仍是
  `7b5152e56ef1139256cecc161a9319261f71db3b63d0a5d61cae82bff5549f48`。
  这是路径/size/mtime的摘要，**不是Parquet文件内容SHA256**。
  本次源stat不变、全部47候选组的ts/symbol列被扫描、
  Reader均显式close，未读OHLCVA，不改Parquet/H5/生产查询。
- 原整月报告保留90个日明细及每组匹配数，约238KB，适于科研核验；
  **不宜直接把用户可编辑的大JSON自动视为受信任生产索引**。

## 本轮代码：只分析已存在的证据，不再耗时读行情源

新增`tools/audit-parquet-month-shared-key-report.py`：
- 只接受本模块`reports/`目录内新旧JSON，输入单份不超过3MiB；
  不能覆盖已存在输出，输出也是本模块新安全JSON；
  `--read-only`为必须显式给出的CLI开关。
- 严格验证月份窗口、2～8只唯一股票、全日期×全证券组合无重复/漏项、
  原全候选源行守恒、各股票和全体键数守恒、每只证券日locator
  组号与匹配键数守恒、源路径相对安全、不重复行组、stat摘要格式、
  源只读/仅键列等原报告标志。
- **可选**`--single-day-report`：对指定日期逐只股票的
  `(source-relative-path,row_group,matching_key_count)`做**严格字典相等**
  对账，要求同源stat清单和同股票集合，任何差异中止，不产生成功报告。
- 只写紧凑聚合：每只股票21个非空日期/9个零键日期、非48键异常候选、
  行组个数的范围和均值、整月跨日唯一行组数，以及单日报告对账状态；
  **不会复制原始90天×每组的全部定位表**，更不会输出付费OHLCVA/
  intraday source timestamp。
- 完全不打开Parquet/H5、私有行情缓存；**对用户可编辑报告作离线自洽
  核验，不能认证原文件本身没被篡改或源stat之外的市场内容**。
  不创建/修改生产索引，不连接自动融合。

这个阶段的重点是：**整月一次键扫描确实复用了跨股票和日期的扫描成本；
但尚未证明建立并持久保留月度全部股票索引有净收益**，且报告不能直接
充当签名索引。避免无意义扩大扫描到全部2026年或2011年。

## Windows验收命令

在仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_parquet_month_shared_key_report.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

完全离线、**不再扫描569万行**的审计和跨报告对账：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-month-shared-key-report.py --month-report "reports\pq-202609-three-symbol-month-shared-5min-keys.json" --single-day-report "reports\pq-20260930-three-symbol-shared-5min-keys.json" --read-only --out "reports\pq-202609-three-symbol-month-shared-5min-offline-audit.json"
```

只需上传新`reports/`安全审计JSON及Windows测试结束摘要。若之前单日
报告的本机名字不同，将`--single-day-report`指向本机真实文件；
如没有该文件，可以先去掉此参数做月内自洽审计，但此时
`single_day_reference_exact_membership_verified=false`，**不能声称跨报告一致**。
如果输出同名已存在，换一个新文件名，不覆盖。

## 后续优先级

对零键工作日09-25仅需权威交易日历**单点核实**，不再对全市场做昂贵扫描。
在正式建设只索引键的持久数据库之前，需要明确真实`stock/day`查询
对数据源扫描的需求，以及成本对比现有按查询显式私有OHLCVA缓存；
索引的内容认证、完整性和重建/回滚都要有保障。

本项目主线仍是历史Parquet优先、H5只读对照、TDX盘后独立可回滚增量；
性能工具支线不应长期阻塞真正主数据读取与后续补缺验证。
