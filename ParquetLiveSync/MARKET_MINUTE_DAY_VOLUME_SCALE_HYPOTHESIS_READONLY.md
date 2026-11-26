# P3.10 六字段原始差异分布与候选成交量单位倍数（只读，不校准）

## 来自真实 Windows 数据的动机

P3.9 在用户 Windows 的固定提交 `ecb55c9edc2f648d480e3b1471df465796b3272f` 完成 **517/517** 测试；对确实存在的三份私有 QMT 探针 JSONL 与当地已有 DAY overlay，得到 **66 个**真实股票日的 SHA/回执绑定六字段原始差异，合计 15906 根分钟，且 2026-11-25 原 9 条隔离不变。用户终端仅打印了每只股票前三个真实日期的成交量和成交额原始相对差值：

- `000001.SZ`、`600000.SH`、`688001.SH` 共九个展示日期，成交量相对差约为 `-0.99`，即原生分钟合计约为 DAY 成交量的 `0.01`。**假设**：两份来源的成交量可能相差 `100×` 单位，而不是同一字段真实成交量不匹配。
- 上述九个样本的成交额原始相对误差约为 `1.8e-8` 至 `4.4e-8`。其余 57 天、所有开高低收误差分布并未随用户前一轮打印；**不能**将九个样本当作已验证的全部 66 天六字段吻合。

需要保留真实证据、避免在数据未完整观测前就引入会改变历史 Parquet/H5 的“统一修正”。

## 新增只读工具

`market_minute_day_volume_scale_hypothesis_readonly.py` 对操作者提供的**真实私有 JSONL、物理 SHA、安全相对路径、证券、日期窗口及实际 DAY 模块目录**，复用 P3.9 的全文件逐行与物理 SHA、当地 DAY state.json/回执/Parquet SHA/目标股票日验收，取得已经通过 P3.9 的原始差异结果。然后：

1. 再次核对 P3.9 的状态/格式、原生分钟来源 SHA、配对来源作用域 SHA、每个配对的 DAY 物理 SHA 与回执 SHA、各自然日行数/状态守恒，以及所有禁止入库授权标记都为 false。只统计 P3.9 严格 **241 根**并且确实有本地 DAY 物理证据的日期，240/部分缺格/自然日无行必须单独计数，不得加入成交量统计；无任何可比较日或没有正成交量的 DAY 时拒绝给出候选。
2. 对每个有正成交量的日期求 `native_minute_volume / local_DAY_volume`，保留实际比值的中位、95 分位（nearest rank）和最大值。
3. **仅评估、不应用**候选倍数 `1×`、`10×`、`100×`、`1000×`：按 `abs(native_minute_volume × 倍数 − DAY_volume) / DAY_volume` 计算每个已配对日的误差，再输出每个候选误差分布的中位、95 分位及最大值。选择“中位误差最低的未批准候选”只供调研；**不**输出“校准通过”。为了捕捉单个异常日，最大值必须与中位数并列展示。
4. 同时提供未经调整的 open/high/low/close/volume/amount 六字段**绝对相对误差分布**，独立列出价格四字段与 amount，以便验证“成交量单位关系”是否只作用于量而非价、额。源文件、DAY 对照或原 P3.9 报告若声明来源认证/正式合格则拒绝，不能对无穷值、布尔数字或不守恒的原始 delta 计算倍数。
5. 报告包含可重算的本次统计作用域 SHA、上游 P3.9 作用域 SHA 与本地分钟文件物理 SHA；它们**不是**供应商签名或原始供应商交易所证据。固定 `candidate_factor_is_approved_calibration=false`、`volume_factor_applied_to_data=false`、`independent_provider_identity_verified=false`、`purchased_feed_units_or_timestamp_calibrated=false`、`six_field_quality_passed=false`、`producer_quarantine_closed=false`、`production_merge_authorized=false`、`market_files_written=false`、`qmt_download_calls=0`。

**本工具从不把 `100×` 实际写入源数据，不下载 QMT，不修改生产 Parquet/H5、源文件、QMT 缓存、定时任务、九条隔离或任何状态回执。** 它只是对两份用户本机现存来源作只读统计假设。

## Windows 命令示例

固定该 P3.10 PR 实际 HEAD 后，将 `PINNED_P310_WORKTREE` 替换为独立工作树目录，再对已知 SHA 的真实 JSONL 运行，例如：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P310_WORKTREE\ParquetLiveSync\market_minute_day_volume_scale_hypothesis_readonly.py" --minute-evidence-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync\work\qmt_1m_probe" --minute-file-relative "000001_SZ-20261014-20261112-2620212c96e35063.jsonl" --expected-minute-sha256 "2620212c96e350630aae8524dec531ef0201e0dc3db7b3d0f9ff0d4547762037" --symbol "000001.SZ" --start-day "2026-10-14" --end-day "2026-11-12" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync"
```

本次最多 22 个候选比较日/证券，三个证券分别独立产生 22 日期统计；综合判断需另外汇总共 66 日期样本，不得把每只股票三天的此前摘要误报为全部日期的正式系数。

## 测试和验收状态

- 新增 **25 项单元测试**，覆盖倍数 `1/10/100`、100 倍中位但最大值异常、量额/价格不一致、原始 delta 守恒、异常 SHA、伪造授权、240 分钟非法配对、未配对日/空 DAY、非有限或布尔数值、重复日期、确定性 SHA 和无写入接口。
- 在隔离 Python 环境复制**完全相同的 Git Blob** 源码与测试，并使用与 GitHub `market_quality_source_proofs.canonical` 同语义的测试辅助桩及 P3.9 API 替身，实际运行 **25/25 OK**。这一结果不等于 Windows 真实 PyArrow/DAY 全链联测。
- 加上 P3.9 已实机通过的 517 项，固定 P3.10 PR 的 Windows 全量验收目标为 **542 个方法、22 个模块**；需由操作者进一步在真实三份 JSONL 上运行，确认所有 66 个已证实配对日的误差分布。不可在结果出现前认定 100 倍适用于全部市场/时间窗口或获得生产修复权限。
