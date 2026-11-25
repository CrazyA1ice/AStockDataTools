# 2026-11-25 九只隔离股票 — 第二阶段 QMT 缓存取证（仅查询，不修复）

## 第一阶段已确认

2026-11-25 用户在 Windows 运行 PR #256 的只读工具：15/15 unittest PASS，原运行回执 SHA256 为 72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837。私有候选 Parquet 物理文件 SHA256 验证为 true；当日已接收 5206 只、隔离 9 只、计划 5215 只。隔离分类：2只 OFFICIAL_DAY_OHLC_MISMATCH（SH605336、SZ300462，均为 open），7只 QMT_RAW_ONE_MINUTE_MISSING（SZ300119～SZ300125）。

这些都是真实的第一次运行结果，不代表第2次访问 QMT 后仍然相同。隔离名单仍保留，data_quality_cleared=false。

## 为什么不能简单重跑

原生产 update_market.py 的 stage_day() 在 daily/YYYY-MM-DD.parquet 和同日 JSON 已存在、且 SHA256 验证通过时直接复用旧候选，不会重新按股票请求 QMT。若要合法修复须另行提出增量、保留旧证据、重新验证官方 DAY、可回滚的修复流程；不能删除候选或清空 quarantine。

## 本阶段诊断工具

新增 audit_market_qmt_cache_readonly.py，必须显式传 --confirm-qmt-cache-query：

1. 固定 2026-11-25 的正式运行回执 SHA256，先复用 PR #256 的审计函数，验证 9只隔离、5206只已接受、候选 Parquet 真实 SHA，才允许访问 QMT；
2. 验证本地 canonical update_market.py Git blob 为 2c510563ad387ab79188ca1d736b63496d187d1b，加载真正生产环境已有的官方 DAY 参考和购买源校准，并复核校准 SHA；
3. 只用一次 xtdata.get_market_data_ex(field_list=OHLCVA, stock_list=9只, period=1m, start_time=20261125, end_time=20261125, count=-1, dividend_type=none, fill_data=False) 取现有数据，不调用 download_history_data()，不安装新行情、不修改 Parquet、H5、状态、隔离回执或计划任务；
4. 对每只返回的数据，在内存中调用真正生产 normalize_frame() 和 normal_qmt_day()，以同一份官方 DAY 和购买校准检查；输出以下分类：
   - CACHE_KEY_MISSING：当前返回字典没有该股票；
   - CACHE_HAS_ZERO_ROWS：返回股票但经规范化无分钟数据；
   - CACHE_FRAME_INVALID：返回帧不符合字段/时间/数值约束；
   - CACHE_PRESENT_STILL_REJECTED：分钟数据可取但仍被生产校验拒绝，附具体原因；
   - CACHE_NOW_VALID_NOT_COMMITTED：现时内存校验可以通过，尚未写库，更不是已修复。
5. 显示官方 DAY 开盘/收盘及 QMT 原始首条 open。两者不直接等同于最终 materialized 开盘价；最终判定始终使用 normal_qmt_day()。若原始开盘冲突持续，应另作 09:30 集合竞价、时间网格、校准和官方 DAY 原始文件对照。

注意：程序自己不调用 QMT 历史下载、不写项目数据文件；xtquant 客户端自身可能维护其缓存/日志，不能称其对 QMT 安装目录绝对无副作用。本脚本也不保证在未登录 QMT 时可用。若查询返回失败，保持全部隔离记录，不自动重试或修复。

## 离线验证

本轮本地已运行 13/13 unittest PASS、Python py_compile PASS。曾发现测试文件在仓库 tests 子目录下进行真正 unittest discover 时导入路径缺失，已经复现失败并修复 sys.path；最终再按与 Windows 相同的目录布局执行 13/13 PASS。GitHub 远端两个 Blob SHA 与实际测试文件匹配：

- audit_market_qmt_cache_readonly.py：40942866ae7366bade0305956df0b2d296d61b3e
- tests/test_audit_market_qmt_cache_readonly.py：8a30948a0f8374a3b5c41cbcad43770e71cd83d1

真实 Windows QMT 缓存查询尚未执行。先在 detached 审计工作树执行 12 项离线回归，再在经 SHA 固定的 canonical 工作目录上运行本工具，反馈完整 9 只 current_qmt_cache_status。本工具独立于 PR #243 和 PR #255，后续确认安全修复方案前不得合并或自动上线。

新增端到端主入口离线模拟验证：在回执与校准均已满足的条件下，恰好一次调用 get_market_data_ex、股票列表正好9只、fill_data=false，download_history_data 零调用，市场数据文件零写入。该测试也已在真实 tests 子目录布局通过。


## 2026-11-25 真实 Windows 初次查询的 CRLF 哈希误判

用户实机 detached worktree 上 13/13 离线测试通过，但实际 QMT 缓存读取前报 CANONICAL_MARKET_WRITER_BLOB_CHANGED_STOP。后续用户只读执行 git hash-object 验证发现工作树和 canonical 文件的 Git Blob 均为 2c510563ad387ab79188ca1d736b63496d187d1b，git diff --no-index 为空。旧审计工具自己对 Python Path.read_bytes() 原始字节计算 Blob SHA；当 Git Windows 配置 core.autocrlf 或换行属性将检出的 LF 文本写成 CRLF 时，Git 对干净的 LF Blob 仍返回固定哈希，但原始 CRLF bytes 的 Python SHA 与它不一致，从而产生误拦截。隔离环境已复现 Git 与原始字节哈希的差异；具体用户本地换行格式尚待新验收确认。

修复仅在 git_blob_sha() 中对已验证没有孤立 CR 的 CRLF 作 CRLF→LF 规范化；实际代码任何其他字节变化仍使固定 Blob 检查失败。新增三项测试验证标准 Windows CRLF 通过、内容修改被拒、孤立 CR 被拒。预计总单测 **16项**，等待用户 Windows 真实复验；不会重写 update_market.py，不放宽最初 11月25日运行回执 SHA 或 QMT 购买校准哈希。
