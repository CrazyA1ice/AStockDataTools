# 2026-10-29：私有日线 overlay 日期键兼容修复

## 主线与阻塞点

本轮继续既定路线：购买 Parquet 是原始只读基线；只对经过精确来源缺失审计的完整证券日，从 H5 私有暂存补齐；以后再提供受控查询、Hikyuu 原生 H5 镜像和通达信盘后增量。不回到历史分钟边界假设研究。

首次审查 `build-parquet-primary-day-overlay.py` 发现：

- `plan-parquet-primary-day-bootstrap-offline.py` 的 `daily_coverage[].date` 来自原报告的 `by_day`，格式 `YYYYMMDD`（例如 `20261008`）。
- `stage-h5-only-day-to-parquet.py` 输出的私有 `manifest.json.day` 是 `date.isoformat()`，格式 `YYYY-MM-DD`（例如 `2026-10-08`）。
- 旧版 `verify_reports()` 把第一种格式不加转换用作 expected 映射键，`inspect_stage()` 又用第二种格式直接查 expected。因此即使 `day.parquet`/SHA/来源都正确，`prepare` 仍会错误拒绝为 `Stage is not eligible`，四日版本无法组装。此前提交里的合成端到端测试如果真正执行，会暴露这处阻塞。

## 代码与回归

- 只在“报告已经由 `gate_tool.analyze()` 校验完成”之后，把候选日期由 `YYYYMMDD` 规范化为 `YYYY-MM-DD`。不改原始报告格式、私有 stage 清单格式，**也不改变任何行情值或源文件**。
- 原端到端 `test_prepare_activate_rollback_does_not_change_original_files` 的预期改为正确的 ISO 日。
- 增加 `test_compact_gate_day_key_matches_iso_staging_day` 验证真实合成报告的紧凑键和 stage ISO 键能够贯通，`test_noncanonical_stage_date_fails_closed` 确保非规范 stage 日期仍然拒绝。其他哈希、重复、污染及临时目录安全检查保持不变。

## 本地验证（Windows，仓库根目录）

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_build_parquet_primary_day_overlay.py" -v
```

**2026-10-29 Windows 回传通过：** 此文件 `Ran 11 tests in 3.196s`、`OK`（原9项+新增2项）；另 `test_stage_h5_only_day_to_parquet.py` `Ran 7 tests in 6.003s`、`OK`。合计18项均通过，无失败或跳过。测试用临时构造 H5/Parquet，不读取 `D:\stock` 的真实商业行情，因此只能证明合成合同和拒绝机制有效，不能证明剩余3天的真实stage已经完成。

在 11 项通过后，依照 [私有四日版本操作说明](2026_PRIVATE_PARQUET_DAY_OVERLAY_VERSIONING.md) 先分别暂存 2026-10-09、10-12、10-13 三日，再 `--action prepare` 组合 2026-10-08、09、12、13 四个隔离清单。成功指标：`private_rows=22191`，`prepared_days` 为四个 ISO 日期，`production_query_route_modified=false`。不能跳过其余三日，也不能把 prepare 当成生产发布。

只上传终端结果与四份 `manifest.json`，不上传 `day.parquet` 商业行情。原数据文件必须保持只读。
