# 2026-10-29：私有日线版本的可控只读消费（尚未自动激活）

## 已验证的前提

用户Windows完整通过此前暂存/版本/单股票查询33/33项及修复后双股票批量查询8/8项。双股票真实SAFE报告`private-day-query-batch-SH600000-SZ000001-20260930-20261013-v1.json`的**实际结果**：SH600000=购买1根+私有4根，SZ000001=购买1根+私有4根，累计10根；仅一次四日H5/PQ现场复核，现场55.981965秒，批次总57.327676秒，使用私有prepare版本SHA `46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`。报告表示源文件未修改、生产查询路径未切换、private active指针未读也未写。

**当前真实证据仅证明“显式SHA查询”。没有用户实际激活私有指针，也没有生成Hikyuu镜像或正式生产Parquet库。**

## 新增机制

现有`tools/build-parquet-primary-day-overlay.py`早已具备私有指针prepare/activate/rollback操作；但`query-parquet-primary-day-overlay-batch-readonly.py`此前始终只能传显式SHA，并不会读取指针。本轮在**该独立实验接口**中新增`--use-private-active --confirm-private-active-read`，不改变正常显式SHA流程，也不触碰正式查询路由。

1. 批量查询只允许两个互斥的选版本模式：**显式**`--version-sha256`；或**双重显式确认**`--use-private-active --confirm-private-active-read`。不能无参数回退、不能两种同时选。
2. 私有指针读取前用现有`safe_private()`检查模块工作目录和软链接，若`.day-overlay.lock`存在则拒绝，以免在已知私有版本更新过程中读取；缺指针、格式损坏、无有效版本或stage SHA损坏均fail-closed。
3. 选中的版本仍先执行完整版本清单/来源报告 SHA 校验、私有stage证券唯一键验证、一次实时H5/PQ完整缺失日核对，以及购买原件优先的逐股票有界查询。**不缓存“永久无冲突”的旧审计判断。**
4. 查询临返回前再次读取同一个私有指针SHA；如在批次中被rollback/activate为不同SHA，直接拒绝整个结果，不写任何SAFE报告。该检查并不是数据库级的跨进程原子事务；需要更高一致性的生产系统仍须设计读写协调，不能因为通过一次检查就宣称正式生产安全。
5. 安全摘要会标注`private_version_selection_mode`、`private_active_pointer_sha_stable_during_query`、`no_active_pointer_change`。主动读取了指针的情况下不能再错误宣称`no_active_pointer_read_or_change=true`。
6. **批量查询本身从不激活、回滚或改写私有指针**；用户真实`work/unified_parquet/active-day-overlay.json`继续保持先前状态。购买Parquet/H5、所有private stage、生成的SHA、分钟线/镜像和生产路由都不修改。
7. 新增6项合成测试：模拟私有指针激活后相同bar输出、指针未设置、查询中变动、非法内容/并发锁、两个模式冲突、显式SHA不读指针。与已有8项组成**14项**。新14项**尚未经Windows实际运行，不声称已通过**。

## Windows下一步：先只做合成测试（无需真正激活任何用户本机指针）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_primary_day_overlay_batch_readonly.py" -v
```

验收要求`Ran 14 tests`及完整`OK`。测试使用临时目录自造H5/Parquet，模拟活动指针激活/回滚，不更改用户市场数据，也不会触碰用户真实private active指针。

原来的实际只读查询命令保持有效，仍可用`--version-sha256 46bd...`查询SH600000和SZ000001。**无须为验证本轮测试而再次花约一分钟真实扫描行情。**

### 后续受控使用说明（不要求用户本轮执行）

只有在用户明确决定将已验收prepared版本设置为**模块私有活动版本**后，才可使用旧versioner的`--action activate --confirm-private-pointer`进行真实激活；该操作还会重新验真四日实时数据、只能更改模块内private指针，需满足prepared版本的`previous_version_sha256`链；如数据源出现新记录会拒绝。相应版本必须由后续消费者明确启用`--use-private-active --confirm-private-active-read`，不能让普通正式市场查询静默走新路径。rollback仅撤销私有指针引用，不删除不可变版本，也不动购买原件。

在用户授权前不要自动或隐式执行任何activation。当前优先将本轮14项合成测试验收后继续推进**独立原生Hikyuu H5镜像**，先做源码兼容与真实Schema/量纲读写隔离验证，禁止把任意HDF5表伪装成Hikyuu原生行情文件。
