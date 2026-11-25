# Financial source-revision recovery P1: offline, non-committing preview

**Status (2026-11-25): SOURCE IMPLEMENTED; TESTS NOT YET EXECUTED ON USER HOST. NOT APPROVED OR DEPLOYED.**

This stage follows PR #244's 53/53 owner-run QMT cache audit and three-stock disclosure evidence. This is a stacked Draft branch based on PR #244 SHA 52b3945a2079d4e190095d62be2a0c9006d73a76. Neither the canonical branch nor PR #243's 20:05 production runner is touched.

## Existing storage contracts

Inspected on canonical code at 2b5c1bd28f8df4d4512dd933e50b1be50741f6a6:

1. qmt_extra_financial_cache_import._prior_rows computes Counter union across every selected, verified, immutable snapshot date. This preserves old variants, not only the latest day.
2. qmt_extra_data._financial_snapshot_file reads active/YYYY-MM-DD.json version pins when available and rejects ambiguous same-day versions without a pin; each pin binds filename, SHA-256, symbol, table and asof.
3. qmt_extra_data._verify_financial_snapshot_file checks schema, row identity and content-addressed snapshot filename.
4. Importer _plan_symbol validates all nine financial tables before commits. Existing qmt_capital_scoped_policy_reader only permits exact-date m_quarter differences with **unchanged report keys**. It does not permit newly added report dates for the four Capital cases.
5. Importer _commit_symbol writes each staged table and active pin sequentially. It is **not** an all-nine-table atomic transaction; any later writer must handle partial execution explicitly.

## Implemented pure preview

Module: ParquetLiveSync/qmt_finance_versioned_recovery_preview.py.

Call preview_symbol with nine-table source records plus a verified history Counter for each of E.FIN_TABLES. The module has NO CLI, no data provider imports, no QMT reads or downloads, no file writes, no ledger mutation, no policy activation.

| Classification | 2026-11-25 observed count | Required proof | Preview only |
| --- | ---: | --- | --- |
| HOLDER_METADATA | 46 | Unique pair for each changed record across complete history/current, exact stable projection, no fields changed beyond declareDate, or type for Top10 tables; endDate unchanged | HOLDER_METADATA_REVIEW_REQUIRED |
| CAPITAL_ADDITIVE | 4 | Exactly one new m_timetag key, none removed, no duplicate current report keys, every old business field retained across all old m_quarter variants | CAPITAL_ADDITIVE_REVIEW_REQUIRED |
| ISSUER_DISPUTED | 3 | Exact name-bound stock/table/20260930 report period, pinned old/current row SHA-256, pinned stable projection SHA-256, unique record pair and exact known change-field set | ISSUER_DISPUTED_REVIEW_REQUIRED |
| Provider UTF-8 error 688259.SH | 1 | No repaired source; never query/preview as a normal pending revision | Continue pending |

All routes additionally reject missing historical records in other eight financial tables, malformed source records or incomplete table sets. New unrelated-table observations are counted but cannot authorize a commit.

Every successful preview result has:
- readiness = REVIEW_ONLY_NO_APPLY_AUTHORIZATION
- allow_auto_clear = false, allow_apply = false
- historical_versions_preserved = true
- candidate_is_parquet_snapshot = false
- pending_state_changed = false, snapshot_state_changed = false
- deterministic preview_sha256 (a plan digest, **not** a signed human approval or Parquet checksum)

## Mandatory writer gates for *a future phase*, NOT implemented

1. Obtain explicit independent human approval for the exact stock, financial table, report period, old/new full-record SHA-256 and evidence. Never auto-approve source taxonomy changes or numeric revisions.
2. Bind current ledger SHA256, every prior immutable snapshot SHA256, active pins and current raw provider-cache SHA256. Reject changed evidence using compare-and-swap (CAS).
3. Stage candidate immutable Parquet files separately; validate Arrow schemas, source record counts and all prior raw variants before any pin updates.
4. Back up current ledger/pins and use a dedicated manual recovery entry point, not the scheduled importer. Build a journal to detect/compensate partial multi-table commits; do not claim _commit_symbol is atomic.
5. Re-running an identical approved new version should be idempotent. Divergent bytes, report keys or ambiguous pins must stay quarantined.
6. Verify all historical content-hash files still exist; only after readback should an approved active pin be selected. Rollback restores active pins/ledger, **never** deletes old immutable snapshots.
7. Enforce China 18:45-23:35 task-protection window, idle scheduled task and existing shared runner mutex. Add no GitHub Actions or new scheduler.
8. PR #243 post-deployment 20:05 acceptance is independent, requiring a same-run receipt and task result. Do not judge it by the 2026-11-24 pre-install task exit=1.

## Known unresolved source risks

- 002328.SZ HolderNum: issuer report supports 57,896 ordinary shareholders for 2026-09-30; QMT latest 57,900, +4, with new declareDate 20261012. Rounding hypothesis is unverified; shareholderA semantic mapping remains unknown.
- 002178.SZ Top10Holder: issuer-backed whitespace variation but QMT type QFII机构 -> 公司 is still not an issuer taxonomy mapping.
- 002310.SZ Top10Holder: QMT source introduced Han 一 in place of the source connector hyphen. Never perform global textual substitution.
- 688259.SH: Top10Holder query 20260930 fails on underlying UTF-8 buffer of 199 bytes ending E5. No lossy decode or broad cache deletion.

## Tests

ParquetLiveSync/tests/test_qmt_finance_versioned_recovery_preview.py has 39 synthetic unittest functions covering all three cohorts, complete nine-table preservation, record uniqueness, field masking, Capital revisions and external-manifest pinning. No QMT, Parquet engine, network or real finance data needed. They are **not claimed to pass until actually executed**.

The completed 53-stock QMT audit does not need to be rerun merely to review this preview implementation.
