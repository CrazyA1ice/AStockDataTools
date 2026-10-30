# 2026-10-30：私有日线批量只读消费者——返回前二次校验stage快照

## 与项目主线的关系

项目的既定路线是：**购买Parquet优先，原始H5只补Parquet真正缺失的完整股票日，先形成模块内独立、可回滚的统一Parquet，再验证真实Hikyuu原生H5镜像，最后接通达信盘后增量**。历史5min细微差异机理研究暂缓，不应把2025/2026日线10股票日的数值倍率候选直接推广为分钟线或生产量纲授权。

前序Windows真实证据：2026-10-08/09/12/13共有22,191条经隔离暂存的H5独有日线；已有准备完成但未激活的私有版本 SHA `46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`。双股票实际批量只读查询曾返回10根（2根购买、8根补缺），四日缺失仅复核一次。真实Parquet/H5文件继续保持只读，正式交易查询路径不变。

## 本轮修复的实际边界

原批量查询在两个环节验证stage：先由`verified_version()`验证整个不可变版本和每个stage的来源SHA/键，然后在`selected_private_rows()`解码选中stage后立刻复核其SHA。**仍存在较窄的TOCTOU窗口**：被选中的stage可能在已解码之后、组合结果返回之前被外部进程替换；即使返回的内存行情是之前的快照，当前模块目录中的不可变stage已不再对应安全摘要。

现在在完成整批购买查询、所有私有stage解码及逐证券合并预算判定之后，返回结果前：

1. 对**本次查询实际选中的**每个stage重新执行模块安全路径约束；拒绝stage文件符号链接、缺失文件。
2. 重新计算`day.parquet` SHA-256，对比已通过完整版本证明的`parquet_sha256`；不重新读取整份表/商业OHLCVA。
3. 任一stage改变立即`ValueError`失败关闭，**整批没有可返回的结果或新增SAFE**；不回退购买源、不静默剔除私有补缺日。
4. 如果日期窗口没有任何私有stage，则结束校验数量为0，不引入多余stage文件哈希IO。
5. 安全摘要增加`selected_private_stages_final_snapshot_reverified=true`与`selected_private_stages_final_rehash_count`，明确本次实际复核的stage数量。

此检查**不构成跨进程事务快照、不能防止最终检查后的瞬时竞态**。既有H5/PQ现场补缺复核、源文件stat前后检查、私有指针首尾一致性检查仍保留；没有永久缓存“源缺失证明”，不修改版本、指针、原始H5/购买Parquet，也不生成真实H5镜像。

## 本轮纯合成测试

原文件`tests/test_query_parquet_primary_day_overlay_batch_readonly.py`共有14项。新增两项，预计16项，等待Windows Python 3.11真实回归：

- `test_final_snapshot_rejects_stage_mutation_after_decode`：使用**测试目录自造**的stage，让原解码与首轮哈希检查完成后才追加字节，要求最后快照门禁拒绝整个批次。
- `test_final_snapshot_rejects_stage_deletion_after_decode`：同样先成功解码，再删除**测试目录自造**的stage，要求失败关闭。

既有正常批量查询用例新增`selected_private_stages_final_rehash_count=1`断言；仅购买数据、没有选中补丁日期的用例要求`=0`。没有使用用户真实市场源。

在仓库根目录 PowerShell：

```powershell
git fetch origin
git switch fix/day-overlay-batch-final-stage-snapshot-20261030
git pull --ff-only origin fix/day-overlay-batch-final-stage-snapshot-20261030
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_primary_day_overlay_batch_readonly.py" -v
```

预期为`Ran 16 tests`且结尾`OK`。若失败，请只回传具体失败栈与测试摘要，**不需要重扫55秒真实行情，不上传付费行情、生产H5或stage内的OHLCVA**。待合成回归通过后，此PR才建议合并。

## 后续真正的主线任务

完成前一轮五SAFE聚合的8项离线测试并归档新报告，再围绕现有22,191条私有日线的**只读消费、原生Hikyuu H5镜像的完全虚构闭环及隔离运行时读取**推进。此前跨2025/2026的10/10股票日只能证明特定候选数值倍率与小样本Hikyuu 2/2原生验证，不足以批准将购买Parquet全市场写成H5，更不能自动激活私有指针或覆盖`D:\stock`。
