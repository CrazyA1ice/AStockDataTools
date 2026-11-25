# 2026-11-25 八周期 9 只隔离股票：只读取证

## 已知正式任务证据（用户 Windows 输出）

- 正式收盘后任务日期：2026-11-25；回执 SHA256：72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837。
- 本次 EIGHT_PERIODS 阶段 exit_code=0，官方 DAY+QMT 分钟接收 accepted=5206，隔离 quarantine=9，合计 expected=5215。初次 owner 原生 PowerShell 诊断标记 Evidence=MATCH，但只是元数据字段一致，不是候选 parquet 文件的物理 SHA。
- 已知样本（其余 4 只未见输出，不得臆测）：SH605336 为独立官方 DAY materialized 开盘价不一致；SZ300119、SZ300120、SZ300121、SZ300122 未取到 QMT 原始 1 分钟 OHLCVA。
- 数据质量仍 EIGHT_PERIODS=PARTIAL、FINANCIAL_DAILY=PARTIAL（177 processed/77 pending/4526 remaining）、ADJUSTMENTS_ROTATING=PARTIAL（80 processed/next batch）、SECTORS=PASS；日常执行 PASS 不能清除市场隔离或替代独立源认证。PR #243 故意要求八周期数据 PASS，尚不能认定为正常轮换。

## 新增工具

audit_market_quarantine_readonly.py 仅用标准库读取当次正式回执、八周期阶段日志、私有 work/market_update/daily/YYYY-MM-DD.json；严格检查固定 run SHA、Scheduled、日期、日志归属 work/、当前日唯一 MARKET_DAILY_STAGED、已接收/隔离数、240行网格对应数、SHA 元数据关联、隔离字典；输出全部被隔离股票及原因分类。不调用 QMT，绝不修改行情、定时任务、数据库、隔离记录。默认为只验证元数据，结果中的 parquet_content_sha_verified 为 false，如加 --verify-parquet 则再以只读方式对候选私有 Parquet 计算实际 SHA256。data_quality_cleared 永远是 false。

测试：在隔离 Python 环境，15/15 unittest 通过、Python py_compile 通过；验证哈希改动、错误日期、日志路径越界、符号名、不一致隔离数量、重复日志、parquet 文件更改、无文件等均 fail-closed。Git Blob SHA 已与本轮本地经测文件逐字节匹配：脚本 9a1cfa1ce6b924687ac3d893b1fc0550cdd6222f，测试 2e12092f469eeeff0bcabd9f2d83d22f9715e116。

## Windows 单行验收

先把本 PR head SHA 固定，使用新独立 detached worktree，不覆盖 canonical 或 PR #243 / PR #255。执行 Python 测试；再针对当天真实回执运行只读取证。输出 reason_groups 和 stocks 里会包含全部 9 只的原因。若物理 SHA 不匹配、stage 日志被覆盖、回执更改，程序报 MARKET_QUARANTINE_AUDIT_REVIEW_REQUIRED，不可自动复写修复。

**门禁**：先获得完整九只及异常类别，再设计只读 QMT 单股票时间网格/官方 DAY 比对；不直接降低 OHLC 容差、改 verify_materialized_ohlc()、删除隔离日志或标记任务全成功。