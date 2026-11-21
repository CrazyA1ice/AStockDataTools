# Finance P4：受限历史财务快照内容指纹与pin SHA只读核验（2026-11-21）

## 前置实测
Finance P3固定SHA `1f8aeebeee26acd0d4db33ef5667c1d5b5099242` 用户Windows `332 tests ... OK`。截至2026-11-21，Capital 42只首阻断中报告期键增删36只，经济/日期字段差异6只。P3在8只代表样本中观察9个快照候选及8个pin，声明压缩大小合计45280字节，未验证内容SHA。

## 本次P4范围
- 新增 `market_center_finance_pending_snapshot_integrity.py`，必填显式 `--explicit-readonly`、`--state-module`、`--market-root` 与此前已人工观察的 `--expected-progress-sha256`。无法匹配账本SHA直接拒绝。
- 调用既有P3边界（8只上限、每首阻断表最早/最晚、状态文件前后SHA、调度保护窗口、符号链接及pin结构核验），对至多32个快照、总压缩字节≤16MiB、每文件≤4MiB执行既有 `qmt_extra_data._verify_financial_snapshot_file` 原始schema、股票/表/asof、内容指纹文件名校验；同时使用Parquet元数据限制解压行数/row group数量和未压缩大小。
- 使用现有 `_financial_snapshot_file` 的pin解析；针对样本的active pin重新计算其引用snapshot的二进制SHA256并核对。对Capital只输出各已保存历史snapshot的报告期键数量/重复/无键数量，不输出原始报告期、股本经济数值、财务数据或payload。
- 无QMT调用、无外部行情参照、无写入、无cursor/pending调整，不激活m_quarter豁免。不声称确认36只股票的当前QMT增删细节；任何历史内容的局部验证不等于财务数据来源真实性。
- 所有异常fail-closed。没有任何正式更新入口或20:05任务改动。

## 回归
新增8项合成临时Parquet测试：schema与内容指纹、pin正确、pin SHA篡改拒绝、文件名指纹错误、账本SHA错误拒绝、超字节预算拒绝、显式只读开关、SHA格式限制。基于P3已通过332项，预计本阶段 `test_market_center*.py` 约340项；**尚未Windows现场验证，请勿宣称通过**。PR保持Draft，不部署、不修改正式业务数据。
