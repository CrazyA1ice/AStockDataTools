# AStockDataTools

> **2026-11-01 最高优先级主线：** 保留原购买Parquet不动，以H5补缺生成新统一Parquet，再从新Parquet生成原生Hikyuu H5镜像并核对day/1min/5min一致，最后以TDX增量更新两者。日线私有版本14,137,981条已验，镜像和分钟仍待交付。详见[主线唯一执行计划](H5ParquetReconciler/docs/MAINLINE_PARQUET_H5_TDX_20261101.md)。


A股行情数据本地处理与校验工具仓库。工具源代码、合成测试和文档在GitHub保存；**付费行情和本地数据库不上传仓库**。

## 工具目录

### [H5ParquetReconciler](H5ParquetReconciler/README.md)

Hikyuu H5 与购买的年度Parquet行情的全量覆盖、时间差集、重叠K线量价冲突核对。当前支持日线、1分钟、5分钟的本地只读报告，并有断点续跑；下一步按需求文档开发格式转换、数据并集以及增量维护。

- [完整需求与验收标准](H5ParquetReconciler/docs/REQUIREMENTS.md)
- [Windows运行指南](H5ParquetReconciler/README.md)
- [数据格式及局限](H5ParquetReconciler/docs/TECHNICAL_NOTES.md)
- [开发路线与当前任务](H5ParquetReconciler/docs/ROADMAP.md)

Parquet冷查询A/B目前支持**反序交叉复核与源文件stat清单指纹检查**：两次基准分别按RowGroup优先、Arrow优先运行，再用[只读反序验收工具](H5ParquetReconciler/docs/2026_PARQUET_COLD_AB_REVERSED_ORDER_AUDIT.md)核对两份安全摘要。仅能判断单次观测方向，不能因此自动切换生产引擎；付费原始行情不上传。

该工具不负责自动认定哪个数据商更正确，也不会直接覆盖原始H5或Parquet。
