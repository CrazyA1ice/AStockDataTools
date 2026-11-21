# 2026-11-21 财务 QMT 断连恢复：限定来源的退出码86

## 起点和已验证事实

- 以 V2G5 固定提交 `c69f97e93188bc3cc455adf271ca994348f7548c` 为基线，继承 PR #221 的财务独立子进程有界重试。
- 用户 2026-11-21 在固定 V2G5 worktree 的 `test_market_center_v2*.py` Windows 合成测试 **312/312 OK**，其中包括 PR #221 的13项专用断连测试；这不证明真实 xtquant 服务已恢复。
- PR #221 原 `main()` 以 `except Exception` 捕获整个 `collect()`，随后通过异常文案前缀判断 QMT 断连。若本地路径/转换/序列化异常恰好也包含相同文字，会被误报为86并触发重复子进程。

## 本次小修复

1. 仅在调用 `xtdata.download_financial_data2` 与 `xtdata.get_financial_data` 的边界，通过 `_qmt_provider_call` 把明确以 `无法连接xtquant服务` 开头的提供方异常包装为 `QMTCacheProviderDisconnected`。
2. 仅该专用异常可在子进程 `main()` 输出结构化 `QMT_CACHE_WORKER_CONNECT_UNAVAILABLE` 并退出86；非 QMT 路径检查、转换、文件系统等异常保留原始失败，不得伪装为重连故障。
3. `UnicodeDecodeError` 仍按既有 exit85 处理；父进程现有总3次连接尝试、2秒/4秒等待、混合错误5次上限、未知exit1立即失败及旧 cursor/快照保护均不改动。
4. 无任何真实 QMT、财务、H5、行情 Parquet、20:05 调度、state/cursor 或 writer 锁修改。

## 测试、发布与后续现场步骤

新增3项仅用合成 xtquant 的测试：本地路径伪相同报错不转86、QMT调用成功后转换失败不转86、真正由 QMT 读取接口抛出的断连仍为86。基于 V2G5 Windows 已通过312项，预计本分支完整命名测试集为 **315项**；本分支尚未运行 Windows 回归，**不能宣称测试通过**。

使用独立 worktree、固定 SHA 回归全部 `test_market_center_v2*.py`；经验证后，仅观察实际 QMT 登录与当前已提交财务版本/游标，制定单独的续跑方案。不得清空 pending/cursor、自动重放失败旧批次、改动正式定时任务，或将缓存读取成功等同于业务语义认证。
