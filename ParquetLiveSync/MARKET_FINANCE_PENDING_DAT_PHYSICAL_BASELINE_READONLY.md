# P3.27：使用 Windows 已验收的第三个物理 SHA 固定本地 Finance DAT 基线（只读复核）

## 实际已验收的上阶段前提（2026-11-28）

P3.26 Draft PR #293 的固定 Git HEAD `90d39257919dc177b244cb0794501097bc368653` 在用户 Windows 下运行成功：

- 项目 `.venv/Scripts/python.exe`，PyArrow 26.0.0。
- P3.26 新增合成测试 **23/23 PASS**；广泛 `test_market_*.py` 发现与运行 **789/789 PASS**（不是早期文档里较窄的 780）。
- 按原进度账本中的 **77 个 pending 股票**限定只读范围，对真正存在的 **616 个 Finance `_7xxx.DAT`** 文件完整物理字节双遍 SHA：每遍 **70,748,048 B**，两遍合计 **141,496,096 B**，均成功。76 个历史来源冲突对应 608 文件／70,457,520 B，单独 1 个解码错误对应 8 文件／290,528 B，零字节 0。
- 第一固定 SHA（保存的 `financial-cache-progress.json`）：`2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`。
- 第二固定 SHA（P3.24/P3.25 的 **DirEntry 元数据清单**）：`b5aa0aa3f0879eabbb65499d962fda3087a090f963399f42b72b13799c8dc711`。
- **第三固定 SHA（P3.26 首次 Windows 实机产出的 DAT 物理字节聚合清单）**：`abea9830387d3b9487b9cd1a5b80d9c7e6da02fae66857b98d91091aff74a856`。

第三个 SHA 是对 `[market,stock,filename,size,mtime_ns,dev,ino,per_file_sha256]` 按既定顺序组成的聚合清单求 SHA；它**不是**直接拼接 616 个 DAT 内容，也不是 QMT 或交易所对来源签发的证明。所有财务原始业务表、9 表覆盖、财报报告期及历史修改事实仍未得到认证。

## 新的安全门槛：三重固定再复核，不改变首次快照

`market_finance_pending_dat_physical_baseline_readonly.py` 必须从命令行传入 **全部三个**外部已核验的 64 位 SHA；任一参数为空、格式错误即在任何 DAT 文件打开之前失败。

检查器直接调用已验收的 **P3.26 `inspect()`**，原样保留 P3.24/P3.25 账本、元数据、边界、路径防逃逸、Windows 内核句柄前后与跨遍身份、两遍真实内容 SHA 以及再次复核；绝不让新模块自行枚举、解析或打开第二套数据来源。P3.26 返回后，验证两个旧 pin、第三个物理摘要、状态和读取规模守恒，并拒绝所有表映射/来源认证/解码/修复/解隔离的越权旗标。

如果任何一个文件的内容、目录元数据、进度账本或 P3.26 约束发生变化，就报错并停止，**不更新第三个原始 SHA**。若 QMT 有合法增量，必须单独组织源历史审阅，不能把新 SHA 覆盖旧 SHA 后继续称之前已经认证。

### 本地命令（只读、依赖已有真实数据，不能在 GitHub CI 复现）

在 **P3.27 独立分支** 的 `ParquetLiveSync` 下：

```powershell
& 'D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe' -B .\market_finance_pending_dat_physical_baseline_readonly.py --module-root 'D:\ChatGPT\AStockDataTools\ParquetLiveSync' --stock-root 'D:\stock' --finance-dir 'D:\software\JHQMT\datadir\Finance' --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a --expected-dat-metadata-sha256 b5aa0aa3f0879eabbb65499d962fda3087a090f963399f42b72b13799c8dc711 --expected-dat-physical-sha256 abea9830387d3b9487b9cd1a5b80d9c7e6da02fae66857b98d91091aff74a856
```

成功仅返回 `physical_baseline_match=true`、聚合 SHA 和数量；失败向 CLI 仅显示 `PENDING_DAT_PHYSICAL_BASELINE_READONLY_REVIEW_REQUIRED`，不暴露原始路径、股票代码、单文件物理摘要或二进制内容。**不提供自动刷新基线、写入、解除隔离、DAT 格式推断、QMT 下载、后台调度或主分支合并能力。**

### 合成测试和验收边界

新增 **16 项**测试：纯 Python 测试 15 项，覆盖三 pin、摘要不一致、旧 pin 漂移、CLI 故障脱敏、字段越权防护、字节预算及数量守恒；第 16 项在具备 P3.26 及 PyArrow 环境时构建一个独立临时 DAT 与临时账本，确实调用 P3.26 双 SHA 两次并核对第三 pin，不触碰真实 QMT。

开发环境的纯 Python 测试可通过；真实 Windows 测试、全量选定测试和 **616 个 DAT 再复核均以未来用户真实运行日志为准，尚未通过，不得写成已完成**。

## 下一来源认证工作所需的证据

P3.27 证明的仅是“本次本地 DAT 文件与首次物理基线一致”。进一步解决 76+1 及九条独立隔离，仍需要来自合规来源的、同一标的与报告期完整 **九张财务表真实原始行**、QMT 财务缓存与业务字段映射、来源身份、时点、保存的旧历史与新数据双向对照，并明确处理 1 项真实解码失败；旧 2026-11-25 定时运行回执的原始物理 SHA 也仍缺失。任何缺一环的情况都只能保持 `financial_pending_resolved=false`、`original_quarantines_cleared=false`，不能签发业务认证或覆盖已购 Parquet。
