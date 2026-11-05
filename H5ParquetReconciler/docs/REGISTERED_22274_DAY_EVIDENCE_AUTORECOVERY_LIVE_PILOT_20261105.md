# 22,274条日线候选：已注册版本的SHA证据自动恢复与真实单日主线验证

2026-11-05。开发分支`feat/purchased-primary-minute-local-query-20261105`。

## Windows已完成的真实验收
- 八周期购买源单证券接口10/10，私有日线显式只读路由13/13，
  不可变版本状态5/5，私有日线来源不重复/价格几何核对15/15，
  合计**43/43**项合成测试PASS。
- 本机已有且通过静态SHA回执校验的私有22,274日线候选注册版本
  `e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23`。
- 注册成功 **≠** 2026-11-05的实时原始H5/购买Parquet复核。
  不要重复物化私有22,274候选，也不要创建生产数据合并。

## 本轮新开发（待Windows实机验收）
- `tools/resolve-registered-day-22274-evidence-offline.py` 从上述
  已注册版本的不可变manifest中提取`mixed_stage_safe`文件名与字节SHA；
  按SHA从既有`reports/`找原始live 83-key SAFE（相同内容多个SAFE
  可稳定按字典序选一个，绝不以最新时间代替SHA）；
  沿live SAFE SHA找2011..2026历史ledger，沿阶段SAFE SHA找88候选离线计划；
  再从ledger SHA绑定的2016和2026来源报告里找精确原始报告。
  最终按live SAFE中的私有索引路径和SHA校验83-key manifest。
- 调用现成`KEYS.verified_existing_plan`及`MIXED.read_verified_key_manifest`
  对所有原始SAFE/私有键做离线重新分析，**不打开H5/Parquet市场行情文件**；
  不仅按文件名或最近修改时间选择证据。
- 可显式`--write-private-config`，在gitignored的
  `work/unified_parquet/registered-day-research-<SHA>.json`
  生成可重复使用的7字段本地证据配置（若已存在且内容完全相同，
  幂等返回；若不同，不覆盖），不会泄露原始OHLCVA到仓库。
- 新增 `tests/test_resolve_registered_day_22274_evidence_offline.py`
  8项全虚构JSON测试：原版SHA解析、配置显式且幂等、年度文件篡改、
  阶段回执不符、重复一致SAFE处理、版本数量不符、拒绝覆盖和缺失计划。
- 一步离线脚本：
  `run-registered-private-22274-day-resolve-evidence-offline.ps1`，
  自动测试和生成私有配置，**不读任何原始行情**。
- 一步完整现场验证：
  `run-purchased-primary-private-22274-day-mainline-live-pilot.ps1`，
  先运行既有日线合成回归及新8项离线测试、SHA恢复证据，
  后显式执行八周期入口的H5/Parquet日线**真实来源重新核验**，
  选2026-10-09单日`SH600000`（此日属于已认证四个整日缺口），
  期望原购买日线0、私有H5整日候选1、mixed候选0。
  仅输出不含OHLCVA价格数值的来源统计；按原日线查询器约定
  可能在`reports/`中新建两份仅含SAFE统计的JSON证明文件；
  **不修改原始行情、不创建H5镜像、不合并生产、不激活生产入口**。
  这一步的H5/PQ完整源键复核可能耗时，不是元数据零扫描。
- **新证据恢复/真实查询脚本尚未通过用户Windows实机验收。**
  如果版本SHA证据不唯一、不匹配或实时来源漂移，只能失败关闭。
  不可静默使用过期候选，也不能在失败时自动关闭验证来凑查询结果。

## 仍未完成
- 对200万以上候选行组的2025`SZ302132`分钟查询优化另行处理；
  本主线不再提高OHLCVA上限。
- 2011年以前至1990左右的H5日线数据与购买Parquet日线覆盖关系尚
  需重新建历史范围审计，本次22,274行只是2016/2026缺失候选，
  不等同全历史日线补齐。
- 交易所官方日历与复权因子语义未认证，不因日线只读查询通过而自动发布。
