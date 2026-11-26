# 通用行情来源证据：本地原始文件字节 SHA 核验（P2 只读）

本功能面向任意日期、SH/SZ/BJ 证券、八周期，核对操作者**明确指定**的本地私有文件是否与声明 SHA256 一致。不是 QMT 下载器、交易所官方数据解析器、供应商签名验证器，也不是生产入库审批器。

## 为什么做这一层

用户 Windows 已完成 PR #265 的 146/146 实机回归，9 只隔离股票日对应 47 个规则事件。原回执里的 accepted Parquet SHA（de113cbd...）和日回执 SHA（eeed821e...）不能充当九只隔离 QMT 原生分钟数据及独立官方 DAY 字节 SHA。必须在长期管理工具中先实现**文件字节证明**，再设计更严格的提供商身份与行情内容解析，不允许只凭两个文件名或来源标签将其认定为独立可信。

## 合同

输入 manifest JSON 必须包含 format=astock_source_byte_evidence_v1、scope（三字段 trading_day、symbol、period）及 2～3 个 artifacts。必须具备 native_minute 和 official_day 两类角色，可选 purchased_reference。每个 artifact 必含 role、source_id、relative_path、expected_sha256。文件均位于用户显式指定私有目录下。

示意性 JSON（哈希值只是占位，实际使用时**必须**替换成文件字节 SHA256）：

~~~json
{
  "format": "astock_source_byte_evidence_v1",
  "scope": {"trading_day": "2025-04-08", "symbol": "SZ300888", "period": "1min"},
  "artifacts": [
    {"role": "native_minute", "source_id": "declared-qmt-export", "relative_path": "QMT/stockday.raw", "expected_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    {"role": "official_day", "source_id": "declared-official-export", "relative_path": "DAY/stockday.dat", "expected_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
  ]
}
~~~

运行示例，路径需换成用户明确授权的私有证据目录和已固定 Git 工作树：

~~~powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_WORKTREE\ParquetLiveSync\market_quality_source_proofs.py" --evidence-root "D:\PrivateEvidence\Example" --manifest-relative "manifest.json"
~~~

本工具绝不主动导出 QMT 缓存、批量扫描全盘、下载行情或上传私有资料。拒绝绝对路径、父级逃逸、符号链接、重复物理文件/硬链接、重复 role/source_id、原始文件相同字节“独立证明”、SHA 不符、manifest 重复键、空文件及超限大小（manifest 64 KiB，每个候选文件 1 GiB）。文件内容读取前后校验设备、inode、大小和修改时点；哈希与解析 manifest 使用**同一份文件字节**，避免读取两次发生歧义。

结果会列出各角色本地实际 SHA、字节数、manifest 本地字节 SHA 和报告规范 SHA。**这只证明本地文件字节与预期哈希一致，不能证明文件确实来自声称的 QMT/官方提供商，也不能证明交易日、证券、周期的内容对应或合法**。因此必须继续保持以下状态 false：provider_identity_independently_authenticated、official_day_content_or_trading_universe_validated、native_qmt_origin_proven、market_data_content_validated、production_admission_authorized、market_files_written。

## 实际测试与后续

在隔离临时目录新建完全虚构的二进制文件与 JSON，真实运行 25/25 Python 标准库单测 PASS。覆盖跨 2015/2026 年份、SH/SZ/BJ、八周期、篡改、SHA 错误、重复 JSON 键、路径攻击、链接逃逸、来源身份伪装、空文件及 CLI 无写入。第一轮曾发现重复 JSON 键错误分类，修复后再次 25/25 PASS。源码与测试 Git Blob 分别为 5943bf7244ff0ff75fd042ff3af1a418a7c06a28 和 919bc2f601c6c85b994d41caefc79116dcec19e4，与本轮实际执行文件一致。

新工具**尚未在用户 Windows 上对真实来源导出件运行**，也未触及九只原隔离记录、正式 Parquet/H5、QMT 自有缓存、Windows 调度任务、企微或 main。后续要开发独立提供商元数据/签名适配器、官方 DAY 文件结构与证券交易日集合校验、原购买校准及全量六字段验证；即使文件字节核验 PASS 也不能批准行情修复或解除隔离。
