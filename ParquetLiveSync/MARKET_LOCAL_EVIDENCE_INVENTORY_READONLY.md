# P3.7 显式私有目录内已有分钟/DAY 来源文件的只读 SHA 索引

## 为什么需要这一层

P3.5 已实现单文件分钟内容验收（434/434 Windows 通过）；P3.6 已实现两份真实物理分钟/DAY 来源的原始数值配对诊断（额外 21 个隔离测试通过，455 项 Windows 联测尚待）。但真实使用还需要**先找到机器上已经存在的私有文件及其真实字节 SHA**。严禁为了“凑齐证据”在没有明确授权时下载 QMT 历史、导出新数据，或把正式数据集中的已接收 Parquet SHA 代替被隔离原始分钟 SHA。

`market_local_evidence_inventory_readonly.py` 只接受操作者**明确指定的已有目录**，一次仅扫描这个目录的一层文件（不递归、不扫描盘符、不默认触及生产 AllCycleAStockData），分别支持以下两种索引：

- `--kind minute`：只罗列直接子文件中的 `.jsonl`，**只证明文件字节 SHA**，不自动宣称是 `qmt_1m_probe` 格式，不读取或解释交易数据。
- `--kind day`：只罗列直接子文件中的 `.parquet`，**不证明来源于官方 DAY**，不对文件结构、交易日、证券全集作任何认证。
- 单个显式目录不得是符号链接/文件系统根，不能有超过 256 个一级目录项、超过 64 个匹配文件、超过 256 MiB 的匹配数据总量或单文件 256 MiB。遇到匹配链接、非法文件、空文件、被修改的文件立即拒绝，不以截断的列表冒充完整成果。
- 结果只打印安全相对文件名、文件字节大小和物理 SHA，单项 `contents_validated=false`、`source_provider_authenticated=false`，全局来源身份、完整交易日、复权/单位校准、隔离解除、缓存写入、市场写入、QMT 下载都为 false。
- 这是一份瞬时的目录索引**不是目录锁定快照**；索引后文件仍可能变化，后续 P3.5/P3.6 必须再次以真实 SHA 完整重验。

## 操作示例

只对操作者确认已存在的证据目录执行以下命令，目录占位符必须换成已有实际目录：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P37_WORKTREE\ParquetLiveSync\market_local_evidence_inventory_readonly.py" --kind minute --evidence-root "D:\ExistingPrivateQmtProbeRoot"
```

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P37_WORKTREE\ParquetLiveSync\market_local_evidence_inventory_readonly.py" --kind day --evidence-root "D:\ExistingPrivateDayRoot"
```

若目录不存在或没有匹配文件，按缺证如实输出或拒绝；不得自动创建目录、调用行情服务或下载。

## 验收

- 新增 16 项隔离测试，**16/16 已执行 PASS**：真实临时文件 SHA、分钟与 DAY 后缀区分、非递归、排序、根目录及符号链接、文件为空、数目和字节预算、读取中变动、CLI 不泄漏路径、无写入/下载接口。
- 已对比隔离环境与 GitHub 的 Git Blob，源码与测试字节相同；全量 Windows 验收目标由 P3.6 的 455 增至 **471**，仍需固定提交实机验证。
- 当前没有用户指定的实际 Windows 私有证据目录内容；本阶段不能把合成样本视为找到了原九条隔离真正缺失的原生 QMT 分钟。独立供应商身份、购买源校准、六字段可比性与八周期恢复门禁依旧未通过。
