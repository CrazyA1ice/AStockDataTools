# 2026-11-25 QMT financial pending audit — observed evidence and recovery gates

**Source:** owner-run Windows PowerShell/QMT cache-only audit of PR #244 \`finance_pending_audit_once.py\`; original stdout supplied in conversation as \`粘贴的文本 (1)(20261125-035919).txt\`. This file is an evidence-based classification summary, **not** permission to change production acceptance policy.

## Snapshot of observed results

- Ledger asof/daily date: **2026-11-24**.
- Pending: **54** securities: **53** SOURCE_HISTORY_CONFLICT plus **1** already-isolated CACHE_DECODE_ERROR (\`688259.SH\`).
- Cache batch reads: **6 batches** of **10,10,10,10,10,3**; each returned no missing stock, 53 audited.
- Complete classification printed before final receipt-read exception:
  - \`DATE_OR_TYPE_ONLY\`: **46** (Top10Holder **31**, Top10FlowHolder **14**, HolderNum **1**).
  - \`CAPITAL_ADDITIVE_KEYS_WITH_PRIOR_VARIANTS\`: **4** (Capital **4**).
  - \`OTHER_FIELD_OR_ROW_CHANGE\`: **3** (Top10Holder **2**, HolderNum **1**).
- Ledger SHA-256 remained **\`4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1\`** under both inner and outer checks; no committed snapshot or cursor update.
- Final output \`COMPREHENSIVE_AUDIT_FAILED\` occurred **after** complete classification because \`receipt_summary()\` read a PowerShell-generated UTF-8-BOM receipt with plain \`encoding="utf-8"\`; \`json.JSONDecodeError: Unexpected UTF-8 BOM\`. This is **not** a failed batch and **not** a regression of PR #243. The code fix is \`utf-8-sig\`, with separate regression tests; **do not rerun 53 QMT queries merely to repair final receipt printing**.

## Priority cases for further evidence

| Symbol | Table | Diagnostic | Next proof needed |
| --- | --- | --- | --- |
| \`002178.SZ\` | Top10Holder | \`name\`, \`type\` differ (one raw record each side) | Same-row economic keys and official holder-name context; no normalization-by-default |
| \`002310.SZ\` | Top10Holder | \`name\` differs (one raw record each side) | Establish whether rename/format/source correction; preserve both raw names |
| \`002328.SZ\` | HolderNum | \`declareDate\`, \`shareholder\`, \`shareholderA\` differ (one raw record each side) | Higher-priority quantitative verification against disclosures; do not auto-accept |
| \`002188.SZ\` | Capital | old keys 108, current 109, +1 key, -0 old, business shared unchanged | Compare provenance of newly added report key while preserving historical m_quarter versions |
| \`002278.SZ\` | Capital | old keys 103, current 104, +1 key, -0 old, business shared unchanged | Same |
| \`002367.SZ\` | Capital | old keys 108, current 109, +1 key, -0 old, business shared unchanged | Same |
| \`002386.SZ\` | Capital | old keys 95, current 96, +1 key, -0 old, business shared unchanged | Same |
| \`002388.SZ\` | Top10FlowHolder | 2026Q3: nine \`declareDate\` values 20261022→20261027; one \`type\` company→institutional investment account; nine mismatched rows, zero ambiguities | Keep immutable old and current raw observations, date/type provenance review |
| \`688259.SH\` | Top10Holder | \`20260930\` single-day query fails UTF-8 at \`xtdata.py:get_financial_data:359\`; 199-byte decode buffer ends \`e5\`, 6 attempts | Request narrow provider-side repair / backed-up targeted QMT cache refresh; no \`errors="ignore"\`, no blanket cache deletion |

The \`DATE_OR_TYPE_ONLY\` category is an **observational projection** that omits \`declareDate\` (and, for Top10Holder/Top10FlowHolder, \`type\`) for diagnostics. Both can be meaningful business/source fields; do **not** silently suppress, reinterpret, or discard differences. These 46 securities had ambiguous_projection_rows=0 in the provided output.

## Safe implementation route (not yet authorized/deployed)

1. Preserve the complete original pending ledger, the original selected Parquet snapshots, and any old active-version pins. Maintain immutable raw versions and comparison provenance.
2. Review the three \`OTHER_FIELD_OR_ROW_CHANGE\` cases first, starting with the quantitative \`HolderNum\` fields. Extract narrow field-level old/current evidence without exposing unnecessary shareholder names or raw payloads; cross-check source disclosures when possible.
3. Define separate, **explicitly scoped** evidence-driven policies for additive Capital report keys and date/type metadata revisions; do not retroactively change default strict import for nine tables or automatically rewrite historical data.
4. Only after backed-up, narrow-scope verification should a deliberate recovery workflow decide whether a pending stock is clearable; retain original, changed and provenance records, fail closed on missing old keys, business quantity revisions, duplicate keys and uncertain mapping.
5. Treat \`688259.SH\` as a separate provider UTF-8 problem. Do not repeatedly query the corrupted 2026Q3 Top10Holder cache, do not manipulate source bytes or use lossy replacement decoding.
6. Run first live 20:05 PR #243 acceptance check independently: evidence must show **post-install run** result and same-run receipt. Historical \`LastTaskResult=1\` from 2026-11-24 remains old evidence and does not prove success or failure of the new runner.

## Version / review constraints

- Canonical deployed code base: \`2b5c1bd28f8df4d4512dd933e50b1be50741f6a6\`, with **two working-tree PR #243 hotfix blobs** installed; do not overwrite them using a hard checkout/reset.
- PR #243 hotfix commit: \`c8f35ed38545ae5bfc20c7d21f26b20394ed54b8\`, still Draft.
- PR #244 is independent **audit-only**, still Draft, not a production deploy. It creates no GitHub Actions, cron, extra task, QMT data writes, notification, or persistent audit output.
