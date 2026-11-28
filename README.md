# AStockDataTools

A股行情数据本地处理与校验工具仓库。工具源代码、合成测试和文档在GitHub保存；**付费行情和本地数据库不上传仓库**。

## 长期产品设计：行情管理与数据质量治理

本工具的长期目标是**管理、清洗、对齐、审计、修复和持续维护多来源、多证券、多日期、八周期行情数据库**，不是为某个交易日单独编写一次性补丁。异常发现之后，应将可复现的故障机制沉淀为通用的分类规则、可追溯候选流程及跨日期/证券回归测试；明确区分只读取证、QMT 缓存写入和正式 Parquet/H5 入库权限。

- [《行情数据管理与质量修复体系设计规范（长期基线）》](docs/MARKET_DATA_QUALITY_DESIGN.md)：范围、证据及 SHA、十类异常、隔离与修复状态机、插件接口、授权门槛、跨日回归和路线图。该设计仍需 PR 审核，不能据此推断生产已具备全部功能。

## 工具目录

### [H5ParquetReconciler](H5ParquetReconciler/README.md)

Hikyuu H5 与购买的年度Parquet行情的全量覆盖、时间差集、重叠K线量价冲突核对。当前支持日线、1分钟、5分钟的本地只读报告，并有断点续跑；下一步按需求文档开发格式转换、数据并集以及增量维护。

- [完整需求与验收标准](H5ParquetReconciler/docs/REQUIREMENTS.md)
- [Windows运行指南](H5ParquetReconciler/README.md)
- [数据格式及局限](H5ParquetReconciler/docs/TECHNICAL_NOTES.md)
- [开发路线与当前任务](H5ParquetReconciler/docs/ROADMAP.md)

Parquet冷查询A/B目前支持**反序交叉复核与源文件stat清单指纹检查**：两次基准分别按RowGroup优先、Arrow优先运行，再用[只读反序验收工具](H5ParquetReconciler/docs/2026_PARQUET_COLD_AB_REVERSED_ORDER_AUDIT.md)核对两份安全摘要。仅能判断单次观测方向，不能因此自动切换生产引擎；付费原始行情不上传。

该工具不负责自动认定哪个数据商更正确，也不会直接覆盖原始H5或Parquet。
