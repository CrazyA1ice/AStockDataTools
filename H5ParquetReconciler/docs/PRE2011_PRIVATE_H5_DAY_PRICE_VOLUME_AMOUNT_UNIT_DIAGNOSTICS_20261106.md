# 1990—2010 H5私有日线：量价金额内部单位一致性诊断（只读）

2026-11-06 · 仓库 `CrazyA1ice/AStockDataTools` · 分支
`feat/purchased-primary-minute-local-query-20261105`

## 已取得不可逆生产写入之前的两份完整证据

1. 原始H5 1990—2010共21年**3,682,327条保守A股代码候选日线**
   均已私有Parquet物化，另有**631,281条其他证券键被排除**。
2. 21年独立只读Parquet文件验收已全部通过：
   年度manifest、完整文件SHA256、字段Schema、日期、
   同年与跨年键唯一性、OHLCVA几何质量全部PASS。
3. 用户2026-11-06晚间Windows日志进一步证实：
   `original_h5_vs_pre2011_private_parquet_exact_candidate_6field_readonly_not_promoted`，
   `years_verified=21`、`exact_h5_source_stockdays_compared=3682327`、
   `all_selected_h5_candidate_keys_and_six_fields_exact_equal=true`；
   原始H5每个股票日、六字段候选算术结果与私有Parquet逐值一致。
4. 这些结果只能证明**文件与算术一致**，不能认证价格÷1000、
   成交量×100、成交额×1000最终代表的真实物理单位、
   复权口径与证券身份。源stat SHA仍不是原始H5的全字节SHA。

## 新的实证诊断

新增 `tools/audit-pre2011-private-day-amount-volume-vwap-unit-diagnostics-readonly.py`：
- 不再重复读取原始H5全部OHLCVA；先重验证三市场H5源stat状态
  和购买日线Parquet全24文件/139RowGroup历史缺口门禁；
  然后读取**已有私有候选**中经过年度manifest + SHA256认证的
  `low,high,close,volume,amount`列。
- 每年按<=16384条进行流式扫描，不写任何市场文件或候选。
  校验物理schema和年度行数，所有量价须有限非负，
  `low<=close<=high`且正价格。
- 如果`volume>0`且`amount>0`，定义**候选隐含成交均价**：
  `implied_vwap=amount/volume`。这是**假设**成交额和成交量
  已经转为兼容的货币/股数单位后的数学比值。
- 检查隐含均价是否在
  `[low - max(0.01, high*1e-8), high + max(0.01, high*1e-8)]`
  范围内。此`0.01`绝对误差仅是候选元计价下诊断宽容，
  **不代表官方行情最小价格精度认证**。
- 同时按`amount/(volume*close)`比率统计各个候选
  `0.01,0.1,1,10,100,1000`倍数周围5%内的条数；
  按年度输出**汇总计数**、超出高低范围计数、双零、
  仅成交量为零及仅成交额为零等四类互斥分区。
  不输出证券代码、原始OHLCVA、个人市场数据或具体日戳。
- 因可能存在不同复权方式、市场时段、历史成交量单位、
  数据供应商口径差异，**超出日高低不是自动判定源数据错误**；
  工具只给出需要追查的证据，不删除、修复或重写任何记录。
- 无论结果如何，
  `h5_physical_amount_and_volume_units_certified=false`、
  `official_adjustment_semantics_certified=false`、
  `production_merge_authorized=false`。

## 实机执行顺序

新增12个完全虚构临时Parquet合成测试：
`tests/test_audit_pre2011_private_day_amount_volume_vwap_unit_diagnostics_readonly.py`，
包括候选量价匹配、低/高价异常、量或金额单边零、
负数或非有限数据、字段Schema错配、文件SHA篡改、
原始来源漂移、年份越界、禁止生产写入等安全门禁。

首轮用PowerShell脚本
`run-pre2011-private-h5-day-vwap-1990-1992-unit-diagnostic-readonly.ps1`
先运行12个合成测试，成功后对**1990—1992年7,959条私有日线**
做真实只读诊断，核对来源指纹、三份年度manifest及Parquet SHA、
金额/成交量统计分区守恒。
预期成功标记：
`PASS_PRIVATE_H5_DAY_1990_1992_VWAP_DIAGNOSTIC=7959`。
真实高低范围外计数未知；**不能因为数量异常而篡改字段
或绕开合并门禁**。

**新工具和12项测试截至提交时尚未经过用户Windows实机验证。**
试点通过后可用同一个Python工具的默认参数扫描1990—2010
全部21年的3,682,327条私有候选，识别年度/时代变化；
之后再独立结合Hikyuu源代码、供应商实证与官方证券信息
确认历史量纲。Hikyuu `H5Record`公开字段定义只明确整数存储
结构，**本身不等于已提供最终成交量/成交金额物理单位证明**。

禁止因单位诊断通过而提前修改购买Parquet、原始H5镜像、
生产活动指针或任何未认证私有历史候选。
