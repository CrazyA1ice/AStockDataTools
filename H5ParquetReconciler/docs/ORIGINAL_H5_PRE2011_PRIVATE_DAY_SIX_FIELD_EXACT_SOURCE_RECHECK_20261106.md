# 1990—2010年原H5与私有Parquet逐条六字段精确回读门禁

2026-11-06 · 分支 `feat/purchased-primary-minute-local-query-20261105`

## 已通过用户Windows实机审计

- 用户新提供的日志显示21年完整私有Parquet独立只读验收全部通过：
  14/14合成回归及21个年度SHA256、来源状态、Schema、
  A股候选唯一股票日、日期、OHLCVA几何等全部成功。
- **3,682,327**条1990—2010年A股代码候选日线已经物化到
  21份本地私有Parquet；**631,281**条其他证券键排除。
- 全量审计结尾状态
  `full_1990_2010_private_h5_day_21_year_files_shas_schema_keys_quality_verified_readonly_not_promoted`；
  `original_h5_ohlcva_redecoded_by_full_audit=false`。
  这就是本轮下一道门禁的理由：私有Parquet完整≠再次从
  原始H5全字段验证候选映射。

## 新增：逐年度原始H5 vs 私有Parquet源数据精确复核

`tools/compare-original-h5-pre2011-private-day-ohlcva-exact-readonly.py`
只读原始H5、已物化私有Parquet、manifest与购买Parquet覆盖门禁：

1. 首先通过既有 `FULL._source_gate`验证三市场H5源stat指纹
   `8abbe4be67525adec7f6e6802aab705f6f79296f7197e66b5e5301827dd3a55a`
   及全部24个购买日线文件/139个RowGroup无2011年前键，
   且Parquet源stat指纹为
   `feca0e42b369106cc32560908d9aa82a472f18cc9a8e846600a5b7b20edc4883`。
   **此stat SHA不是原文件完整字节SHA；不代表来源全部字节经认证。**
2. 对全部私有目录执行已有21年路径完整性门禁；每年以已有
   `FULL._check_manifest`重新验证历史当年单文件SHA256、
   真实年度固定候选/排除数量、未认证标志及源指纹。
3. 每年最多40万条候选记录在本机内存中排序，按
   `(symbol,ts)`生成键索引，拒绝重复。检查完整Parquet
   Schema、空值、证券编码形式、字段来源标签，不把
   证券代码或原始OHLCVA回显到控制台。
4. 逐个打开`sh_day.h5`、`sz_day.h5`、`bj_day.h5`
   的真实H5原生按股票数据集，**只读所选自然年日期切片**；
   每个证券每年时间键长度<=366，核对合法日历、
   严格日期升序和源原生键与H5 compound数据键完全一致。
   保守A股代码候选纳入，其余指数/B股等仅计数，
   不读取非候选OHLCVA。
5. 对纳入A股的每个日键，以UTC+8午夜换算毫秒，
   与私有Parquet对应证券/日期键一一对应，不能漏行、多行、
   重复或跨年；读取该证券当年<=366条原H5 compound记录，
   用原始整数重新计算价格÷1000、成交量×100和
   成交额×1000的**当前候选公式**，要求开高低收、
   成交量与成交额**六字段逐值float64位模式完全相同**。
6. 每年与独立源清单的固定证券数、日期数、
   A股候选日线数及其他证券排除数严格守恒；
   之后再次核验Parquet完整文件SHA及原始H5来源状态。
   该程序从不写入任何Parquet、manifest或源文件，
   不激活生产指针，也不另建市场H5镜像。

### 为什么不直接声明量纲已认证？

“原始H5整数 × 当前公式 = 私有Parquet值”的测试，只证明
**转换代码正确执行了之前声明的候选算术**。价格/成交量/
成交额的源单位是否确实对应这些乘数，仍需要原H5格式定义、
独立重叠行情样本、同日量价及跨周期量纲证据确认。
历史证券上市/退市身份、官方交易日期、复权和公司行为同理
保持未认证标记。通过后`ready_for_production_merge`依旧是
`false`，原H5和购买Parquet主库均不修改。

### 首轮Windows试点与后续推广

- `tests/test_compare_original_h5_pre2011_private_day_ohlcva_exact_readonly.py`：
  **15项虚构H5/Parquet合成测试**，涵盖单字段价格、
  成交量/成交额候选系数错误、日期/证券键错配、
  重复、源值异常、SHA/来源状态变化、受限年份及
  生产安全等情况。
- `run-original-h5-pre2011-1990-1992-six-field-exact-private-day-audit-readonly.ps1`
  首先执行合成测试，通过后只读实机**1990—1992年**
  共**7,959条A股候选**，其他证券键1,866条；
  成功标志 `PASS_ORIGINAL_H5_EXACT_PRIVATE_DAY_1990_1992=7959`。
- 试点通过以后，同一个只读Python复核器可以通过
  `--from-year 1990 --through-year 2010`执行**21年全量逐条
  原H5↔私有Parquet数值对照**，预期总候选3,682,327条，
  其他证券键631,281条。不需要重新生成私有分区。
- **新复核工具及15项测试尚未经过用户Windows实机验收**。
  遇到异常严格失败关闭，不自动修复或放宽质量门禁。
