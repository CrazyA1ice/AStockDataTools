# 2026-10-31：购买Parquet日线字段语义独立证据门禁（阻断生产转换）

> **状态：BLOCKED / NEED_EXTERNAL_VENDOR_EVIDENCE。** 本文件是证据需求与后续实施准入条件，不是一份字段解释字典，也不是历史H5转换许可。不得把README、测试中的候选系数、浮点类型或本文件自身当作供应商合同。

## 已完成的用户Windows实机事实

1. 用户已验收1990—2010年 **3,682,327** 条历史H5日线原生整数全量私有RAW Parquet、21个年度的文件SHA及原H5逐值核对。所有原始购买Parquet、原H5及生产指针始终保持不变。
2. 1992/1993/1995七条真实H5原整数日线经独立Hikyuu **2.8.1/core311** 隔离`Query(index,index+1,DAY)` 原生读取并HMAC **7/7匹配**；这**不是**购买Parquet物理单位认证。SAFE：`reports/pre2011-historical-native-core311-hmac-dededf90b775.json`；PR #179 已合并main `901ea7526bc18dd96c32da5a72736b211f73b8ce`。
3. 已有2026-09-30两股真实购买Parquet↔原H5整数精度检查：原OHLC×1000和volume÷100候选精确对应，**amount÷1000 0/2能直接整数匹配、2/2需要舍入**。这是数值观察，不说明供应商amount物理单位或合法舍入方式。不能直接以四舍五入填数或写H5镜像。
4. **本轮PR #180**：Windows `py_compile` 和**9/9 synthetic unittest OK（0.625s）**；真实购买`AllCycleAStockData/day` **24个Parquet日线文件**的页脚只读扫描成功，**139个行组**，页脚记录数量之和 **14,115,707**，**没有读取一条行情行**；全部24文件**1种Arrow schema**：`symbol=string`、`ts=int64`、`open/high/low/close/volume/amount=double`，`code`字段出现文件数=0。**表级及字段级元数据候选角色**：`price_unit`、`volume_unit`、`amount_unit`、`adjustment_basis`、`timestamp_unit`、`timezone`、`vendor_data_version`及generic单位 **全部0**。这只表明扫描器所支持的标签名不存在于schema/footer元数据中，不意味着供应商无外部合同或官网说明。SAFE：`reports/purchased-day-vendor-metadata-footer-b169f9eaa27c.json`；PR #180 已合并main `580b39cd004afd40f2b0f33bc2f36acce800fe23`。

## 从供应商获得哪些资料

优先取得**原始提供方发布的可追溯版本化字段说明**：产品/数据包名称、购买/更新批次、版本号、发布URL或原PDF及日期、适用的数据分区范围。不能把别家数据商的标准或一般股票交易所说法写成此批数据事实。

| 字段/问题 | 必须得到的明确说明 | 当前证据 | 门禁 |
| --- | --- | --- | --- |
| `open/high/low/close` | 货币种类、价位单位及小数精度，收盘价是否调整，以及前复权/后复权/不复权口径和基准日期 | Arrow `double`，现代H5样本×1000候选 | **UNKNOWN** |
| `volume` | 股、手、张还是其他单位；每一证券类型/交易所/历史时期是否相同，是否含盘后/特殊交易 | Arrow `double`，现代H5样本÷100候选 | **UNKNOWN** |
| `amount` | 元、万元、成交额定义及精度、舍入规则、是否与volume/价格复权一致；如何表示零值和无交易 | Arrow `double`，两真实样本整数刻度**需要舍入** | **UNKNOWN** |
| `ts` | 是否Unix epoch毫秒、UTC/北京时间转换规则、自然日标签及盘后/夜间/休市边界、日K日期口径 | Arrow `int64`，此前真实footer时标候选 | **UNKNOWN** |
| `symbol` | 市场及证券类型代码映射，代码复用/更名/转板/除权调整事件，上市前或停牌记录处理 | Arrow `string`，保守A股候选正则不是证券主数据 | **UNKNOWN** |
| 数据覆盖 | 2011起日线的缺失、停牌、退市、证券扩展、历史更正及补偿规则；提供方是否授权历史补录到私有统一数据视图 | 原始购买day最早2011-01-04（已验收footer） | **UNKNOWN** |
| 数据序列 | 原生Parquet是否做价格/成交量复权，OHLC、volume、amount是否对应同一交易口径；历史是否变更规则 | H5的原生解码和原生RAW仅7条检查 | **UNKNOWN** |

## 对任何历史正式转换器的硬性约束

- **未经供应商字段说明和独立版本核验，`vendor_units_certified=false`、`price_adjustment_basis_certified=false`、`vendor_amount_rounding_approved=false`、`historical_security_master_certified=false`，最终`ready_for_normalized_historical_parquet=false`、`ready_for_h5_mirror=false`。**
- 证据资料应保存为**不含源行情原值**的私有引用清单（URL、正式文档版本、获取日期、校验SHA256）并进行人工审核。供应商正式文档内容如含版权或合同敏感信息，不能直接提交GitHub；Git中只放最小必要的可公开来源描述。
- **不要**对原购买Parquet已有证券日键进行转换回写或覆盖；统一数据仅能在`H5ParquetReconciler/work/unified_parquet`另行生成新私有版本；原购买优先，H5只补确认的整股票日缺口。
- 逐版本明确`raw H5 uint32/uint64 -> normalized`的每字段公式、单位、精度、舍入/截断和溢出/异常策略；需要历史不同市场/时期不同规则时应分组审计，不得强行套用现代日线倍率。
- 即使获得正式供应商说明，仍须以独立的真实有限跨源重叠样本测试，核对未舍入价格/数量/金额可逆性、时间标签、证券合法性及不复权/复权口径；任何不一致仍隔离而非替换原购买文件。
- 1990—2010年历史原H5只读RAW完整并不等于正式统一Parquet已经完成，更不等于可以生成或覆盖生产H5。

## 向供应商请求正式字段说明（可复制发送）

**标题：请提供所购A股多周期Parquet数据的字段单位、复权与时间戳说明**

您好！我已购买贵方的A股日线、5分钟线和1分钟线Parquet历史数据，正在建立只读校验与私有数据备份流程。为避免将不同字段口径错误合并，烦请提供适用于此数据产品及版本的正式字段文档或下载链接，重点是：

1. `open/high/low/close` 的币种、单位、小数精度与复权口径；是否所有年份和周期一致？
2. `volume` 的物理单位（股、手等）、`amount` 的物理单位（元、万元等）、金额精度及舍入/截断规则；遇到零成交和缺失值如何表示？
3. `ts` 的时间单位、时区、日线及各分钟周期的开始/结束标签规则。
4. `symbol` 的市场及证券代码规范；停牌、退市、历史证券类别变化或代码复用如何处理？
5. 是否存在跨年或跨证券类型的口径变更，以及是否提供数据版本、修订日志和正式schema字典？

如方便，请提供与我购买的批次相对应的**原始产品字段说明（PDF/网页/技术文档均可）及文档版本**。感谢！

## 下一步准入（不要继续重复扫描历史倍率）

获得供应商文档后，先**单独**核对文档适用的产品、批次和年份；再针对amount舍入、volume物理单位、时间标签和复权作有限独立交叉验证。若供应商无法提供这些信息，历史RAW继续保持隔离可读，2011年以来购买Parquet仍作优先源；不要在证据不全时猜测标准化全量转换规则。
