# AStockDataTools

A股行情数据本地处理与校验工具仓库。工具源代码、合成测试和文档在GitHub保存；**付费行情和本地数据库不上传仓库**。

## 工具目录

### [H5ParquetReconciler](H5ParquetReconciler/README.md)

Hikyuu H5 与购买的年度Parquet行情的全量覆盖、时间差集、重叠K线量价冲突核对。当前支持日线、1分钟、5分钟的本地只读报告，并有断点续跑；下一步按需求文档开发格式转换、数据并集以及增量维护。

- [完整需求与验收标准](H5ParquetReconciler/docs/REQUIREMENTS.md)
- [Windows运行指南](H5ParquetReconciler/README.md)
- [数据格式及局限](H5ParquetReconciler/docs/TECHNICAL_NOTES.md)
- [开发路线与当前任务](H5ParquetReconciler/docs/ROADMAP.md)

该工具不负责自动认定哪个数据商更正确，也不会直接覆盖原始H5或Parquet。
