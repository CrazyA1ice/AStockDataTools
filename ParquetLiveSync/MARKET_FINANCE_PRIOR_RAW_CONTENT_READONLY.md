# P3.21：原财务快照的 Arrow 行身份、JSON 记录和旧历史并集只读核验

## 已有实机验证的边界

P3.20 固定 `e7f55afcf0acbee20ab6f81064dde9e930f79ece` 用户 Windows 验收：旧审计器 15/15、P3.20 新专项 19/19、29 个选定测试模块 **682/682 PASS**。原保存财务缓存进度文件固定 SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`；76 个严格由 `pending` 内部已识别冲突字符串推导的 `table/stock` 文件范围，**全部存在原旧 `snapshots` 目录**，共 91 个历史 Parquet 文件／1,310,172 物理字节，91 个 `active` 指针均和相应旧文件物理 SHA 匹配，真实清单哈希 `12be02042231302b6e1334797eb5751c52971e6497f1b42d5be03ae97095bcb8`。分布：`Capital` 14 个范围／28 份旧快照、`HolderNum` 3／3、`Top10FlowHolder` 25／25、`Top10Holder` 34／35。**P3.20 没有解析任何 Parquet 原始行内容**。

前一阶段 P3.19 从同一个固定账本的 77 个待审项得出 76 条历史来源冲突和 1 条解码异常；76 条中 62 是股东持股有关表旧历史行缺失或修订，14 是 Capital `REPORT_KEYS_ADDED_OR_REMOVED`，**不是可以允许的 `M_QUARTER_ONLY_CANDIDATE`**。这些分类仅来自被哈希锁定的存储账本，不是独立 QMT 新源与旧源逐记录核对。

2026-11-25 原定时运行回执固定 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 仍未恢复；P3.14／16／17 实际日志、阶段及 Parquet 物理 SHA 关联不代表原回执身份已验证。原九条行情隔离及财务 76+1 项待审均维持不变。

## 原生产只读语义（无需访问新 QMT）

原 `qmt_extra_data.RAW_SCHEMA` 规定 Arrow 五列 `asof:string`、`symbol:string`、`item:string`、`index:int32`、`payload_json:string`；原 `_verify_financial_snapshot_file` 会校验 schema、正行数、每行观测日期与股票及财务表一致、`index` 序列及从规范化行内容重算的 `YYYY-MM-DD-16hex.parquet` 文件名指纹。这一指纹**不同于**物理 Parquet 文件 SHA，物理 SHA 由 P3.20 单独校验。

原 `qmt_extra_financial_cache_import._prior_rows` 在不同已选历史观测日期上按 `Counter` 的 **逐行最大重复次数** 合并原始记录；从每条 `payload_json` 解析出字典后，原 `_rows` 去除来源 `_index` 字段后进行规范化 JSON 内容计数。**既不能把每次历史日期的行数简单相加当并集，也不能把两个日期同一行只作无重复集合**。

## 新 P3.21 独立只读审计

命令需要两个独立已核实的 SHA：

`market_finance_prior_raw_content_readonly.py --module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a --expected-snapshot-manifest-sha256 12be02042231302b6e1334797eb5751c52971e6497f1b42d5be03ae97095bcb8`

- 前后**两次**运行已验证的 P3.20 `PRIOR.inspect`：必须仍是同一固定 76 源冲突作用域、快照物理清单 SHA，且每一个旧文件历史日期有唯一匹配物理 SHA 的 active 指针；若中间文件增删、版本/指针改变或清单变化，拒绝。
- 再次校验进度文件物理 SHA 和原身份、只从其 `pending` 中精确识别表/股票，扫描这些已存在的 `qmt_extra/financial/<table>/<stock>/snapshots` 直接目录；拒绝链接或丢失的任意父级，不扫描无关股票或新来源目录。
- 对每个选中的旧文件在 Arrow 读**之前**核验 `ParquetFile` schema、metadata 行数（单文件最多 20 万行）、压缩后元数据声明的解码大小（单文件最多 64MiB）；总计最多 **100 万行／256 MiB 解压前估算字节／256 MiB JSON 原始 payload**，单条 JSON 最多 1 MiB；还继承 P3.20 128 作用域／4096 文件／单文件 24MiB／物理 Parquet 总 512MiB 上限。真正读取后复用原 `_verify_financial_snapshot_file` 校验内容身份与不可变文件名指纹。
- 解析旧 `payload_json` 时只接受字典、`_index` 字符串、有效标准 JSON、无重复对象键与无 NaN／Infinity。对已选历史日期的旧记录复用原 `_rows` 计算规范化行 `Counter`，在每个确切表/股票范围执行按元素**最大重复次数**的旧历史并集；聚合输出四表作用域、旧文件数、行数、并集不同记录数和含重复计数及一个不可逆摘要，不打印任何私有股票身份、完整 JSON 或新财务来源记录。
- 每个选中文件在原始 Arrow 内容读取前、后均通过物理 SHA 验证，旧文件全清单事后再次用 P3.20 原规则完整验证。结果仅允许 `old_selected_historical_counter_union_computed=true`，其他 `new_finance_source_consulted=false`、`new_and_old_finance_records_compared=false`、`financial_provider_authenticated=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false`、`qmt_download_calls=0`。

## 验收与不可声称的结论

本阶段独立增加 **21 项**仅用临时目录/合成 Arrow Parquet 和 pending JSON 的单元测试，含单文件验证、历史行重复最大合并、零冲突、目录缺失、双固定 SHA 错误、active 缺失／同日多版本、Arrow schema、股票行身份、文件名内容指纹、非 JSON／缺 `_index`／重复 JSON 键／NaN、内存和行预算、元数据漂移、事后清单改变、CLI 不泄露路径和无生产写入调用。此前 29 模块 682 项已经实机通过；P3.21 的目标为新增后 **30 模块 703 项**，另旧原审计器 15 项，**P3.21 新测试、全回归和 91 份真实旧文件内容校验尚未在用户 Windows 运行**。

即使完成本阶段，也只能证明**既有历史不可变 Parquet 内容及其内部保守并集**；由于仍没有从独立 QMT 新来源取得原始记录，本阶段**不能**算出新数据丢失旧数据的真实差异、也不能批准 Capital 或股东相关表豁免、解除 77 项财务待审、原九条行情隔离、补造原定时回执或改行情/定时任务。所有 PR 保持 Draft，禁止合并 main。
