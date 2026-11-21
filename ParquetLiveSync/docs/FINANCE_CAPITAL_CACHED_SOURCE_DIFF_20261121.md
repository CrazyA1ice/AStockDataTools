# Finance P5：两只Capital疑难股票，旧快照 vs 当前QMT已有缓存的单次只读比较

## 前提
Finance P4于2026-11-21用户Windows固定SHA `029632080b3bd3a85e4476edcfae81805e107e37` 验收340/340 OK：8只样本，9份旧快照内容地址、schema及记录身份已验证，8个active pin的SHA256已核验；合计1052行/45280压缩字节。P3确认42只Capital首阻断中36只是报告期集合变化，6只是业务/日期字段变化。即使本地快照指纹通过，也不说明QMT当前缓存或源头可信。

## 目的与边界
增加 `market_center_finance_capital_cache_compare.py`，需同时显式提供 `--explicit-readonly` 和 `--explicit-qmt-cache-read`，以及canonical状态模块、市场根目录、精确账本SHA。任意缺失或账本变化fail-closed。北京时间19:50–20:25禁止扫描。

先重用P3验证账本SHA和8组元数据，随后从账本中只选择 **2只 Capital**：报告期增删类1只、业务/日期字段改变类1只；优先复用P3样本。每只重审本地所有相应Capital历史候选快照，文件名指纹、schema、行身份由现有P4/底层validator核查，遵守每类范围和总计最多8文件、8MiB压缩预算。只构造选中旧版的Counter并集，不覆盖任何不可变版本。

之后启动最多2个15–30秒受限的独立Python子进程，每只只调用 **一次 `xtdata.get_financial_data([stock], [\"Capital\"], start_time=\"\", end_time=\"\", report_type=\"report_time\")`** 读取QMT现有本地财务缓存；没有 `download_financial_data2`、没有任何其他下载/历史更新接口，且不向磁盘写缓存输出。子进程只将各条记录每字段的规范哈希，通过被父进程捕获的管道传递，不将原始财务值/报告期输出到终端、文件或GitHub。返回值预算3MiB，每只缓存记录≤2000且字段≤128；异常、超时、非法回复立即失败关闭。

父进程按规范哈希比较旧报告期键集合与当前缓存、共同报告期下的业务字段差异、历史多版本间业务字段冲突、仅m_quarter变化的可能性。只输出计数、变动字段名称与受限股票标识；任何比较结果只代表 **当次QMT现有本地缓存**，不能保证源头完整/更新及时、不能证明九表全部一致、不能批准忽略旧冲突或更改财务pending。对账本SHA在QMT调用前后再核验；出现变更则拒绝公布对比结果。

本P5为现场用户主动触发，绝不自动部署或运行于20:05。全部输出标记 `download_calls=0`、`can_repair=false`、`market_file_writes=false`、`source_authenticity_certified=false`。

## 验收
新11项纯合成测试；此前P4已实机通过340项，因此预计匹配 `test_market_center*.py` 的全量是351项。**本P5尚未现场Windows验收、没有调用真实QMT、没有读取真实财务缓存**。请先固定提交离线回归后，再自行判断是否显式进行一次只读cache-read。PR保留Draft。
