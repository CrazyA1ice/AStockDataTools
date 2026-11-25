# 通用行情质量规则内核（P0）使用与验收

> 设计依据：[《行情数据管理与质量修复体系设计规范》](https://github.com/CrazyA1ice/AStockDataTools/blob/design/market-data-quality-reusable-policy-20261125/docs/MARKET_DATA_QUALITY_DESIGN.md)，仓库级设计 PR #263。**P0 是规则预览，不等于完整诊断/修复系统已上线。**

## 用途和边界

`market_quality_engine.py` 不预设某一天、某只股票或固定 5215 只证券，也不将 241 条认作所有周期/来源的通用格式；只使用经上游接入适配器验证、明确提供的证据进行规则分类。它仅支持纯 Python 标准库，不加载 `xtquant`、`pyarrow`、QMT 专用配置或任何付费数据。不查询互联网、不写日志/Parquet/H5/收据、不触发重试/下载/定时任务/企微推送。

输入 `--evidence-json` 为**本机私有的** UTF-8 JSON 对象或对象数组。每个对象：
- 必填 `format=astock_market_quality_case_v1`、`trading_day=YYYY-MM-DD`、`symbol=SH|SZ|BJ + 六位数字`、`period`（八周期之一）、`source_id`（供应商/数据集标识）、`source_state=READY|UNAVAILABLE|UNKNOWN`；
- `official_stock_day` 必须取自独立官方交易股票集合，`null` 是证据不足，绝不以周末/节假日猜测；
- `observed_bars` 和 `expected_bars` 为适配器所测的非负整数，`grid_complete` 必须是按该来源时标、该周期真实交易格点验证后的布尔值；`241`、`240`、`48` 不能被所有周期硬编码共用；
- `raw_source_sha256` 是**原始来源文件或源快照实际字节**的 SHA；`official_reference_sha256` 是独立参考源实际字节 SHA。若缺少，传 `null` 并标记未验证；不能把诊断 JSON SHA 填进去；
- `calibration_verified`、`calibration_drift_confirmed`、`receipt_integrity_valid`、`source_conflict`、`cross_period_consistent` 由独立前置验证器提供，不能靠猜测自动设 `true`；
- `zero_prefix_bars`、`zero_prefix_verified`、`quoted_open`、`first_traded_open`、`official_open`、`traded_hlc_verified`、`tail_hlc_verified` 用于**首真实成交开盘候选**，价格必须为有限正值；同官方价严格比对仅使用 `abs_tol=.0002, rel_tol=0`，并要求零成交前缀和交易后 HLC 都有证据。满足也只能输出候选，不能更改 240 分钟/原始 241 分钟或准许入库；
- `fields_within_tolerance` 是已由来源适配器按**现有真实校准、原有容差**验证的六字段布尔映射。规则内核不会重新测量或放宽容差；如果未提交全部六项，应输出证据不足，不把第一个 `open` 错误遮蔽的其他字段宣称成功；
- `volume_amount_pair_valid` 来自原始正成交量/成交额配对核验；两者一正一零的情况应作为异常。

输入对象可包含适配器专有额外字段，这些字段会参与诊断 JSON 指纹，但不会被通用规则解释成已校验的结果。规则可以**同时**报告多个异常，不是一股仅能归入一个原因。

## 一份完全合成、无需 QMT 的输入示例

将以下内容保存为任意本机测试 JSON 文件，比如 `D:\ChatGPT\scratch\quality_cases.json`：

```json
[
  {
    "format": "astock_market_quality_case_v1",
    "trading_day": "2025-06-18",
    "symbol": "SZ000001",
    "period": "1min",
    "source_id": "synthetic-qmt",
    "source_state": "READY",
    "official_stock_day": true,
    "observed_bars": 239,
    "expected_bars": 241,
    "grid_complete": false,
    "raw_source_sha256": null,
    "official_reference_sha256": null,
    "calibration_verified": null,
    "receipt_integrity_valid": null,
    "fields_within_tolerance": {
      "open": false,
      "high": true,
      "low": true,
      "close": true,
      "volume": true,
      "amount": true
    }
  },
  {
    "format": "astock_market_quality_case_v1",
    "trading_day": "2024-09-25",
    "symbol": "SH600000",
    "period": "day",
    "source_id": "synthetic-tdx",
    "source_state": "UNAVAILABLE",
    "official_stock_day": null
  }
]
```

运行（路径自行替换为已保存的私有测试文件）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\ParquetLiveSync\market_quality_engine.py" --evidence-json "D:\ChatGPT\scratch\quality_cases.json"
```

默认始终只产生 `READ_ONLY_TRIAGE_NO_IO` 的分类与建议。示例应报告时间网格和开盘字段冲突、来源 SHA 与校准未验证，以及另一来源不可达和官方交易日证据不足。即使没有任何 detected rule，`quality_state` 也只能是 `UNVERIFIED`，不是正式的 `PASS`。输出 `input_evidence_json_sha256` 必须标成 `NORMALIZED_CASE_JSON_NOT_PROVIDER_RAW_BYTES_OR_SIGNATURE`。

## 持续处理流程与长期验收

1. 对任意用户给定的日期范围/证券/周期/来源，由上游读取适配器先做快照/交易日历/校准/原始 SHA；本模块仅分类生成结构化的多异常事实和“只读下一步”建议。
2. 后续把这些分类写入版本化的**私有**问题登记簿/跨日待复核队列，并与每日任务和 GUI 状态统一显示；本 P0 暂不写登记簿。
3. 源恢复、QMT 缓存历史下载、私有候选写入、正式 Parquet/H5 合并是不同能力/授权，不能由 P0 规则输出触发。先用不改动原始来源的候选与原来的 `normal_qmt_day` 等生产验证器重验。
4. 目前已有的 2026-11-25 首成交价候选和七只缓存缺口只是**历史测试事实**；后续变更应增加多个不相关日期与证券的正反合成测试，并让原专项检查逐步调用通用规则，而不是把新发现继续硬编码进专项脚本。
5. P0 验收以独立 Python 单元测试、跨日期证券八周期的参数化、不同来源冲突、多种异常并存、错误凭据 fail-closed、默认零下载零写入、目标 JSON 输入不被改动为准。**P0 通过不能当作 P1 适配器、P2 真实来源修复、P3 生产事务已经通过。**

## 与已有 2026-11-25 草稿 PR 的关系

PR #256～#262 原问题回执、只读 QMT 实机证据、首成交临时候选及七股缓存补取门禁继续保留。所有涉 QMT 有副作用操作仍要求显式权限；`--approve-qmt-cache-write-exact-seven-nov25` 仅适用于那条旧专项试验路径，不得作为新通用规则的默认参数，也不能隐式授权修改生产行情。

通用接口后续必须支持任意经独立证明的范围，并在真实修复后更新规则而非只处理 2026-11-25。根设计 PR #263 单独面向 `main`；本代码 PR 与原行情草稿分支堆叠，二者未合并前不能宣称长久设计已在生产强制生效。
