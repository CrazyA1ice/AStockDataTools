# 2026-10-31：供应商日线字段定义的私有证据登记与Fail-Closed准入

> **截至本文件创建时，未收到提供者正式数据字典，禁止启动1990—2010年历史RAW的标准化写入或新的H5镜像。**
>
> 本轮不是更多行情扫描：实现离线文档证据登记 + **始终拒绝自动历史规范化**的公共准入函数。它不能替代人工审核，也不会修改既有2026年私有Prepared Overlay逻辑和活动指针。

## 真实依据（用户Windows已验收）

- 1990—2010年3,682,327条原生H5日线保存在独立原生RAW私有Parquet中，21年原值/SHA整体验收。
- 历史1992/1993/1995七条通过隔离CPython3.11/Hikyuu2.8.1原生KRecord HMAC，7/7匹配，只证明H5解码可核对，不证明付费Parquet的量纲或复权。
- 2026-09-30购买Parquet与原H5两股：OHLC、数量对候选倍率可精确匹配，但amount从float64候选到H5原始整数0/2无损、2/2涉及舍入；暂不能批准自动舍入。
- PR #180用户Windows 9/9合成通过，购买day原文件24个（139行组、页脚行数14,115,707、没有读取任何行情行）、一套Arrow schema（OHLC、volume、amount都是double；symbol string；ts int64），识别到的字段单位、复权、时区、版本元数据角色全部0。SAFE `reports/purchased-day-vendor-metadata-footer-b169f9eaa27c.json`。供应商**外部正式说明是否存在，仍未知**。
- 文档索取清单：`docs/2026_PURCHASED_DAY_VENDOR_SEMANTICS_EVIDENCE_GATE.md`。

## 本轮程序交付

`tools/audit-vendor-semantics-evidence-intake-offline.py`提供两个不读市场的动作：

1. `--action plan`：只读取先前已验收的购买日线Parquet**页脚SAFE**，验证24文件等源状态、认证均为false及元数据角色完整性；输出目前**13类**所需官方字段解释全部缺失的脱敏计划。此前页脚SAFE只是一份证据快照，plan不重新接触任何原Parquet/H5。
2. `--action intake`：只有将**真正取得的供应商原始PDF/HTML/TXT/Markdown文件**和私有来源笔记放入`H5ParquetReconciler/work/vendor_semantics/`后才可使用。笔记必须记录原文档SHA256、产品版本引用、购买批次引用，以及13类字段的`documented/unknown`与原文页面/章节定位；将输入文档整字节SHA与笔记严格比对。只输出**已找到声明的字段类别名**和未覆盖类别名、文档/笔记SHA；绝不输出原文、卖家标识、产品批次、原始声明内容、具体价量额或原文件路径。文档真实性、适用批次和是否具有合同权威都**尚未审核**，只是可核对的私有资料索引。
3. `require_normalization_authorization(...)`：任何输入（包括伪造`certified=true`字段）均抛出`PermissionError`；**当前发布没有授权历史标准化的接口**。未来只有专门的、审过原始供应商文档并经过独立真实数据对照的显式新版本才能解除，不能靠填几项JSON或只看到文档摘要自动解锁。

本轮绝不生成标准化Parquet、H5镜像，不更改生产和私有active指针。只写新`reports/`SAFE，不覆盖已有结果。原始卖家文件和私有笔记全都在Git忽略的`work/`中，**不得上传私有资料或商业行情到GitHub**。

## Windows操作：每条都是一整行PowerShell

**第一步：只运行11项纯合成测试（测试文件使用假PDF文本和假SAFE，不读取你购买的文件）**：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/vendor-semantics-evidence-intake-gate-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/vendor-semantics-evidence-intake-gate-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-vendor-semantics-evidence-intake-offline.py H5ParquetReconciler\tests\test_audit_vendor_semantics_evidence_intake_offline.py; if ($LASTEXITCODE -ne 0) { throw "证据准入脚本语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_vendor_semantics_evidence_intake_offline.py" -v; if ($LASTEXITCODE -ne 0) { throw "11项测试失败，停止真实SAFE读取" }; Write-Host "供应商证据准入11项合成测试全部通过"

**第二步：第一步全部通过才运行现有真实元数据SAFE的纯离线计划**：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\vendor-semantics-intake-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-vendor-semantics-evidence-intake-offline.py --action plan --footer-safe "H5ParquetReconciler\reports\purchased-day-vendor-metadata-footer-b169f9eaa27c.json" --out $out --offline-no-market-read; if ($LASTEXITCODE -ne 0) { throw "证据计划安全门禁失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.required_semantic_roles_total -ne 13 -or $r.undocumented_required_role_names.Count -ne 13 -or $r.private_vendor_document_supplied -ne $false -or $r.historical_normalized_parquet_authorized -ne $false -or $r.hikyuu_h5_mirror_authorized -ne $false -or $r.original_purchased_parquet_or_h5_accessed -ne $false) { throw "供应商说明缺口报告或硬性禁止开关异常" }; Write-Host "供应商字段说明缺口SAFE：$out"

## 将来拿到供应商文档后如何登记

把真正购买该数据产品时的PDF等原始卖家文件放入：
`H5ParquetReconciler/work/vendor_semantics/`（自动被Git忽略），并用PowerShell `Get-FileHash -Algorithm SHA256` 计算原文件SHA。

在同一私有目录创建`source-loci.json`（**不得提交Git**），其格式是：
```json
{
  "format": "private_vendor_semantics_source_loci_v1",
  "document_filename": "vendor-original.pdf",
  "document_sha256": "替换为实际64位小写SHA256",
  "product_version_reference": "购买产品名称及准确版本或unknown",
  "purchase_batch_reference": "购买批次/日期等私有识别，若未知则标明unknown",
  "role_loci": {
    "price_currency_and_unit": {"status": "unknown", "section_locator": ""},
    "price_precision_and_tick": {"status": "unknown", "section_locator": ""},
    "price_adjustment_policy_and_basis": {"status": "unknown", "section_locator": ""},
    "volume_physical_unit": {"status": "unknown", "section_locator": ""},
    "amount_physical_unit_and_currency": {"status": "unknown", "section_locator": ""},
    "amount_decimal_precision": {"status": "unknown", "section_locator": ""},
    "amount_rounding_and_null_policy": {"status": "unknown", "section_locator": ""},
    "timestamp_epoch_unit": {"status": "unknown", "section_locator": ""},
    "timestamp_timezone": {"status": "unknown", "section_locator": ""},
    "timestamp_bar_label": {"status": "unknown", "section_locator": ""},
    "symbol_market_security_type_and_reuse": {"status": "unknown", "section_locator": ""},
    "historical_version_and_rule_changes": {"status": "unknown", "section_locator": ""},
    "covered_product_batch_and_data_period": {"status": "unknown", "section_locator": ""}
  }
}
```
只有供应商文档真实给出了该条定义，才将对应`status`改为`documented`，并在`section_locator`注明页数或章节（不会随SAFE上传）。材料不明确应继续填写`unknown`，**切勿为通过门禁猜测定义**。

然后可运行以下纯离线登记命令，输出仍是**未认证**SAFE：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\vendor-semantics-document-inventory-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-vendor-semantics-evidence-intake-offline.py --action intake --footer-safe "H5ParquetReconciler\reports\purchased-day-vendor-metadata-footer-b169f9eaa27c.json" --vendor-notes "H5ParquetReconciler\work\vendor_semantics\source-loci.json" --out $out --offline-no-market-read; if ($LASTEXITCODE -ne 0) { throw "私有供应商文档登记拒绝" }; Write-Host "未认证来源清单SAFE：$out"

**此次阶段完成不等于文件说明已经到手，更不等于全量转换成功。** 后续需核对原供应商PDF的产品、批次、时间范围和各字段具体含义，再开展真实有限重叠日独立复核、金额取整风险评估，最后单独经用户授权才允许在模块私有目录创建新版标准化历史Parquet及独立H5镜像。
