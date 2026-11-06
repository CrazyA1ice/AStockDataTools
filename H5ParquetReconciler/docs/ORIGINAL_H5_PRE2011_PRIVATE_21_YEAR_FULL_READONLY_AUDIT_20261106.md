# 1990—2010年原H5日线 21年私有Parquet 全量独立只读验收

2026-11-06 · `CrazyA1ice/AStockDataTools` ·
`feat/purchased-primary-minute-local-query-20261105`

## 来源和全量私有物化已经完成

根据用户Windows实机日志，原始H5 1990—2010年保守A股代码候选
**3,682,327个股票日**已全部物化至本地Git忽略的
`H5ParquetReconciler/work/unified_parquet/historical_pre2011_daily_pilots/`
各年度独立私有Parquet（21个年度，1990—2010，逐年SHA256回读）。
另有**631,281个其他证券原生日期键**被排除，而非丢失或识别为A股。

最后一个2010年真实Windows批处理验收：
- `PRIVATE_H5_YEAR_PASS=2010 STOCKDAYS=392395 OTHER_EXCLUDED=109860`
- 私有Parquet SHA256:
  `05e3fe86eca4ead10cb52b3b8e4e3d3a4434c99bc5043a22ea42e37bce2f9a32`
- 批次结束`all_private_year_checkpoints_verified=true`，
  `original_h5_and_purchased_parquet_modified=false`，
  `production_activated=false`。
- 这些是转换阶段的年度验证，并**不是**跨年度全量独立验收。

## 本轮新增独立只读验收

`tools/audit-original-h5-pre2011-private-21-year-day-readonly.py`：

1. 读取原始H5三市场日线stat状态指纹，必须仍等于之前原始H5
   历史盘点的 `8abbe4be67525adec7f6e6802aab705f6f79296f7197e66b5e5301827dd3a55a`。
   购买Parquet日线24文件/139RowGroup用已有来源验证器
   再次物理核对，原始来源stat指纹仍需等于
   `feca0e42b369106cc32560908d9aa82a472f18cc9a8e846600a5b7b20edc4883`。
   H5和Parquet来源只读，**原始来源指纹是size/mtime聚合，
   不是原始文件完整字节SHA256**。
2. 私有候选根目录中必须**恰好有1990—2010年21个候选目录**；
   每年恰好一份`day.parquet`和`manifest.json`；
   拒绝候选目录重复、未知文件、符号链接、缺失manifest或候选。
3. 对每年Parquet重新计算**完整文件字节SHA256**，
   与不可变manifest中SHA严格一致。核对候选行数、
   排除其他证券数、不同日期数、来源指纹、价格/成交额候选
   比例及`not_promoted`、`not_certified`字段；对1990年和
   1991—2010年不同原始pilot format分别精确认证。
4. 不调用先前年份的`annual(...,write=True)`转换函数，
   **不重新生成Parquet**，直接按最多32768行/批流式读取
   已物化的私有候选。完整验证物理Schema字段/类型、
   空值、时间UTC+8午夜、日期年份边界、股票代码语法、
   同年A股保守代码候选、每个股票/日唯一性、年度真实
   股票数量、候选证券数、不同日期数及市场SH/SZ/BJ分布。
5. 所有开高低收/成交量/成交额列必须为有限、非负数；
   四价必须为正且开盘/收盘落在最高/最低的几何范围中。
   证券身份/量纲没有获得官方认证，**仅属结构基本质量检查**。
6. 各年度的日期都严格限定于自身自然年，因此“本年
   股票日无重复 + 各年时间边界不交叉”构成跨年度股票日
   唯一性的完整证明，无须构造368万条全局驻留键集合。
7. 完成后再次验证原始H5和购买Parquet来源stat；
   总量必须**恰为3,682,327**候选股票日和
   **631,281**其他证券排除键；只输出年份/条数/
   私有文件SHA和不含证券身份及OHLCVA的汇总JSON。

`tests/test_audit_original_h5_pre2011_private_21_year_day_readonly.py`
是**14项虚构21年临时Parquet测试**，覆盖完整通过、
各年度缺失、额外分区、日/代码重复、错年/非午夜、
负成交量、源标签变更、SHA篡改、来源状态漂移、
1990独立来源门禁、虚构量纲认证与生产合并拒绝等。

Windows入口：
`run-original-h5-pre2011-full-21-year-private-day-audit-readonly.ps1`。
先运行上述14项测试，通过后**只读实机全部21年**，
逐年输出 `READONLY_PRIVATE_H5_YEAR_PASS=YYYY`；
最后校验21年的聚合汇总及所有安全标志，成功时输出
`PASS_FULL_PRE2011_PRIVATE_H5_DAY_AUDIT=3682327`。

**本轮新增脚本与测试尚未经过用户Windows实机验收。**
如果任何一年SHA/键/行情几何不符合预期，独立审计将拒绝，
不会修改、删除或“自动修复”任何原始及私有行情文件。

## 这轮验收不能代替的后续质量认证

- 此轮读取私有Parquet的全部OHLCVA，但**不逐条重新读取原H5
  OHLCVA对照**。原转换阶段有原生H5逐条读取和Parquet roundtrip
  检查；后续还需一个单独的逐批原H5↔私有Parquet字段级重验器
  （与当前独立文件审计并行互补）。
- 未使用第三方证券历史上市/退市主数据，未用官方交易日历
  认定停复牌合法性；只是代码和日期形式认证。
- 价格÷1000、成交量×100和成交额×1000是数据工程
  **候选变换**；尚须通过同源单位文档、同时间可核对样本
  与跨周期金额/成交量一致性等证据取得认证。
- 未认证复权规则、股本变化、公司行为、跨年度估值口径。
- **严禁因为此脚本成功而自动把1990—2010年私有候选并入购买
  Parquet主库、激活生产查询或反写Hikyuu H5镜像**。
