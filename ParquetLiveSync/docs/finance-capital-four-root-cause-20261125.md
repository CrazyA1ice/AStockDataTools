# Four Capital blockers: selected snapshot multiplicity and economic-field diagnosis

**Status: read-only diagnosis developed, owner Windows verification pending.**
Branch is stacked on Draft PR #246 at commit d405f8bc144c03907837eb852cd3be7d54e39d1f. It does not change the production scheduled updater, existing strict preview policy, immutable Parquet snapshots, active version pins, QMT cache, or 54-entry pending ledger.

## Direct evidence from owner's Nov 25 first five-stock pilot

- 117/117 offline tests passed; all five symbols returned from one existing-cache-only QMT worker request.
- One symbol met the nine-table **review-only** condition: 002178.SZ Top10Holder. It has NOT been cleared and does not have manual authorization.
- Four symbols were BLOCKED, as designed:
  - 002188.SZ target Capital: HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY.
  - 002310.SZ Top10Holder: OTHER_TABLE_HISTORY_LOSS_Capital.
  - 002328.SZ HolderNum: OTHER_TABLE_HISTORY_LOSS_Capital.
  - 002388.SZ Top10FlowHolder: OTHER_TABLE_HISTORY_LOSS_Capital.
- Final ledger SHA256 unchanged: 4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1.
- These errors are **strict source-history multiset checks**, not proof that business values were corrupted or that data was lost on disk. A previously seen raw Capital record missing from *the current provider response* may be an alternate m_quarter version, or it may be a genuine economic/report-key change. Do not remove the safety guard before distinguishing them.

## The question to prove, for exactly four symbols

We need four types of read-only evidence:
1. Identify the exact selected active snapshot file per asof date and its file hash, including whether multiple same-asof immutable versions were pinned.
2. Distinguish one raw row repeated **within a selected snapshot** from the same row appearing in several different daily snapshots. The importer's history uses Counter union (elementwise MAX), not addition across snapshot days.
3. Compare historical vs current Capital report keys (m_timetag), classify removed/new report keys, duplicate current report keys, historical duplicate raw rows, and economic business values while ignoring only the suspect m_quarter provider-private field **for diagnosis**.
4. Compare raw revisions within shared report keys and count m_quarter-only differences. Output cryptographic fingerprints and counts, never raw economic values or shareholder names.

The new qmt_finance_capital_four_diagnostic_once.py does exactly one cache worker request for **002188.SZ**, **002310.SZ**, **002328.SZ**, **002388.SZ**, skipping known UTF8-invalid **688259.SH**. It uses production E._financial_snapshot_rows / E._financial_snapshot_file / F._prior_rows to reverify the already selected immutable snapshot bytes and selected-history union. If the two union calculations disagree, it fails closed. All per-stock results are buffered until final ledger integrity verification.

### Evidence classes (all keep pending unchanged)

| Class | Meaning | Immediate action |
| --- | --- | --- |
| REPORT_KEYS_MISSING_FROM_CURRENT | one or more historical report dates not in current cache | keep quarantine; investigate source coverage |
| CURRENT_DUPLICATE_REPORT_KEY | repeated report key in current cache | keep quarantine |
| HISTORICAL_BUSINESS_CONFLICT | old variants differ in business fields beyond m_quarter | keep quarantine |
| SHARED_ECONOMIC_FIELD_CHANGE | business values changed for common report key | compare official disclosures, no override |
| HISTORICAL_RAW_DUPLICATES_REVIEW | historical Counter includes exact raw repeats; per-snapshot evidence will identify origin | review rows and source semantics; no automatic deduplication |
| ADDITIVE_REPORT_KEYS_REVIEW | old report keys retained, new keys added, shared economic fields preserved | can consider separate manual versioned-review path only |
| M_QUARTER_OR_RAW_VERSION_REVIEW | raw record changes without current shared-key economic changes, often m_quarter variants | manual scoped version provenance review only |
| RAW_MATCH | raw historical Capital multiset equals current | no Capital exception required for this comparison |

The script prints CAPITAL_ROOT_CAUSE (up to four items), CAPITAL_FOUR_ROOT_CAUSE_SUMMARY and CAPITAL_DIAG_LEDGER_UNCHANGED_VERIFIED. Each selected snapshot is associated with asof, filename, SHA256, counts and duplicate metrics, not with raw payload content.

## Operational gates

- Ledger SHA256 must still equal the pinned 2026-11-24 audit epoch. If the 20:05 production run has advanced it, STOP before QMT rather than resetting data; a separate read-only rebaseline should be designed.
- Existing Windows runner guard enforces the task idle state, checks deployed production Git file blobs, and acquires Local\AStockDataTools2005AllStages before any test or QMT access. Protected period is 18:30–23:35 Beijing.
- The one-command runner stages code from exact Git blobs into a unique temporary directory; executes **142** offline tests (117 previously owner-validated + 25 new Capital diagnostics); only then reads four symbols' existing cache. All private Parquet and pending state remain read-only.
- No --apply, no deletions, no source downloads, no GitHub Actions, no scheduled-task changes.
- A diagnostic status does not authorize a mutation or pending clearance. The earlier PR #245 pure strict preview remains unchanged. PR #246 remains Draft and its one successful stock remains review-only.

**Next decision:** interpret these four per-stock output distributions before designing a safe, tightly scoped Capital multiset policy. Do not conflate field-level economic equality with proof of provider or issuer authenticity.
