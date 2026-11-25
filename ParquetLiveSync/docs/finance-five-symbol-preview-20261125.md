# Five-stock source-versioned recovery preview P2 (cache-only)

**Status:** implementation committed, 15 offline pilot tests **not yet confirmed passing on owner Windows after fix** on owner's Windows environment. This is not a recovery/repair process or a data import. No approved version is selected and no pending record is removed.

The owner's 2026-11-25 102/102 offline suite succeeded with FINANCE_LEDGER_UNCHANGED_VERIFIED. This follow-up derives from the versioned recovery pure preview developed in PR #245, with a narrow QMT cache-only pilot.

## Immutable evidence epoch and selected pilot

This pilot refuses to run if the private finance pending ledger differs from SHA256:

4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1

This is the November 24 daily-date ledger previously verified with 54 pending stocks. If tonight's 20:05 scheduled task advances the ledger normally, the pilot **must stop** rather than silently using stale evidence; a new, separate read-only rebaseline would then be needed.

| Symbol | Table | Mode | External evidence or history context |
| --- | --- | --- | --- |
| 002178.SZ | Top10Holder | ISSUER_DISPUTED | Name-space correction and unresolved QFII机构→公司 taxonomy |
| 002188.SZ | Capital | CAPITAL_ADDITIVE | Old 108 report keys retained, one new key, historical m_quarter raw variants |
| 002310.SZ | Top10Holder | ISSUER_DISPUTED | Hyphen-minus vs Han ideograph 一 in a holder name |
| 002328.SZ | HolderNum | ISSUER_DISPUTED | Issuer supports period-end ordinary shareholder count 57896, QMT cache 57900 |
| 002388.SZ | Top10FlowHolder | HOLDER_METADATA | Nine 2026Q3 date/type revisions, stable other fields |

Known UTF-8-invalid 688259.SH is **never read** in this pilot.

## What the pilot actually does

1. Under the scheduled-task idle check and existing runner mutex, verify current deployed PR #243 code file blobs and canonical branch HEAD; enforce China 18:30-23:35 guard.
2. Stage Git-blobs of seven prior audit/preview sources, two new pilot files and the signed-by-Git-content (but **not human-signed**) 3-case evidence manifest into a unique temporary folder. Verify each staged blob SHA. This does not require switching the canonical branch or discarding the deployed PR #243 working-tree hotfix.
3. Run 117 **offline** unit/integration tests (27+21+8+46+15). A failure stops before QMT calls.
4. Verify the historical 54-stock pending ledger SHA256 and exact five target-table reasons. Preserve the 688259 known provider decode pending entry.
5. One existing QMT cache-only worker call for five symbols, nine tables each, with a 120-second timeout. No download API. Fetch the union of selected historical snapshots via the production F._prior_rows reader that verifies snapshot identity/file hashes.
6. Call pure P.preview_cohort to validate all nine tables. A strong review-only result is not approval or import authorization; blocked conditions remain blocked.
7. Print only per-symbol result classes, historical-version counts and content SHA256 fingerprints, plus the aggregate preview hash; no raw shareholder names or QMT records. Verify private pending ledger SHA256 is unchanged under both Python and PowerShell finally checks.
8. Remove temporary working copies; never write Parquet or update active snapshot pins.

## Future writer rules (not implemented)

- Approval must be explicit, case-specific and independently grounded in source record hashes and issuer/field evidence.
- Staging, immutable snapshot version creation, active pin selection, ledger transition and receipt logging need a crash-safe journal and compare-and-swap safeguards. Existing F._commit_symbol is only sequential per table and must not be called as a transaction engine.
- All previously selected snapshots remain immutable. Version rollback means active-pin/ledger rollback, never deletion of original versions.
- This preview cannot accept UTF-8-invalid 688259 or silently normalize numeric shareholder data.
- PR #243's first post-deploy 20:05 job remains an independent acceptance task.

## Expected output and interpretation

- FINANCE_OFFLINE_117_TESTS_PASS: all synthetic offline tests finished successfully.
- PILOT_REVIEW: code reached a narrowly scoped evidence review outcome only. No approval granted.
- PILOT_BLOCKED: code did not meet the input/source evidence gates; keep it quarantined. A pilot containing blocked entries can still be diagnostically complete.
- PILOT_SUMMARY: reports five outcomes plus reproducible audit hash. No Parquet write.
- FINANCE_246_FIVE_STOCK_PREVIEW_COMPLETE_NO_DEPLOY: test and diagnostic runner completed without runner error, not evidence of successful production data import.
- FINANCE_LEDGER_UNCHANGED_VERIFIED: preserved ledger SHA256. It does not prove absence of unrelated background modifications in other systems.

## 2026-11-25 owner-run test failure and fix

The first owner-side 116-test run passed the old 102 tests and 13/14 pilot tests. The deliberate ledger-tamper test, `test_ledger_mutation_is_detected_even_after_worker`, raised its expected integrity exception but found that `FINANCE_FIVE_STOCK_PREVIEW_COMPLETE_NO_COMMIT` had been printed **before** the final `finally` ledger SHA256 comparison. The PowerShell wrapper correctly stopped **before any live QMT cache read**, and confirmed the actual ledger unchanged. This is an execution-status ordering bug, NOT evidence of market-data corruption and NOT proof that the live five-stock preview passed.

Fixed: now the Python success-completion message and normal return occur **after** the `finally` integrity check; if the ledger hash changed, it raises and never emits the success marker. Added a separate assertion that verified-ledger output precedes the completion marker; also adjusted the previously misleading source-drift test to mutate one numeric QMT field **after** freezing the expected manifest, verifying the actual source-row SHA256 gate. Pilot tests now number **15**; total offline suite now **117**. The owner has not yet reported the rerun after this fix. No data was changed or repaired by this commit.
