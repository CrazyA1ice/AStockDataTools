# P3 Capital quarter variants: tightly scoped REVIEW-ONLY recovery preview

Status 2026-11-25: implemented in Draft branch only. NO production deployment or automated data recovery. The new offline tests are source-controlled but NOT YET owner-executed.

## Evidence verified in owner's 142/142 tests and four QMT cache queries

All four selected snapshot pairs (2026-11-17, 2026-11-18) were checked against active version pins and content SHA256, and the Counter-MAX union reconciled with the production reader. No identical raw Capital record duplicates exist in their selected snapshots.

| Symbol | Old Capital report keys | Current report keys | Historical distinct raw rows | Historical variants by report key | Identical raw duplicates | Removed report keys | Shared economic changes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 002188.SZ | 108 | 109 | 110 | 2 | 0 | 0 | 0 |
| 002310.SZ | 146 | 146 | 147 | 1 | 0 | 0 | 0 |
| 002328.SZ | 88 | 88 | 91 | 3 | 0 | 0 | 0 |
| 002388.SZ | 106 | 106 | 108 | 2 | 0 | 0 | 0 |

002188.SZ additionally has one new Capital report key, 20261119. The first five-stock versioned pilot's error HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY could arise from ANY of the nine financial history tables because the historical Counter parsing stage iterates through all nine tables before the Capital target. **The originating table has NOT yet been identified.** Do not misattribute this to repeated historical Capital rows or soften the raw multiplicity check.

## Implemented compatibility: only three evidenced (symbol, target-table) tuples

- 002310.SZ / Top10Holder
- 002328.SZ / HolderNum
- 002388.SZ / Top10FlowHolder

In the pure no-write versioned preview, Capital is a NON-TARGET table for these three cases. Previous immutable Capital raw versions may differ only in m_quarter for the SAME m_timetag report key, while all other fields match exactly. The source raw rows remain untouched and separately available. This does not apply to Capital as the primary target: the existing strict additive-key Capital rule remains unchanged.

Every gate below is mandatory:
1. Complete nine-table histories and current cache. Every historical raw Counter item remains valid and has multiplicity exactly one; no raw duplicate waivers.
2. Cross-table Capital historical and current m_timetag report-key sets MUST be identical, with zero added and zero removed keys.
3. Current Capital must contain exactly one row per report key. Historical variants may repeat a key only if all business fields except m_quarter are identical.
4. Every shared historical/current economic field must match exactly. No tolerance, rounding, missing fields, or normalization.
5. A non-listed (symbol, target-table) tuple with raw Capital mismatch is blocked with CROSS_CAPITAL_UNREVIEWED_SYMBOL_TABLE_SCOPE. Unchanged Capital source rows can still pass for other cases.
6. Every other non-target table (Income, Balance, CashFlow and holders etc.) retains the original strict history-preservation check.
7. Primary target record revisions must still meet unique-pair and field-scope checks; 002310 and 002328 must ALSO match their exact prior/current raw-row SHA256 in the PR #244 issuer evidence manifest.
8. 688259.SH remains hard-quarantined due to QMT Top10Holder 20260930 UTF-8 provider error.

Returned evidence includes cross_table_capital_quarter_proof counts, preserving historical raw variants. All outcome flags remain allow_apply=false, allow_auto_clear=false, pending_state_changed=false and snapshot_state_changed=false, regardless of classification.

## Investigating 002188's unknown duplicate source

The five-symbol pilot now emits PILOT_HISTORY_MULTIPLICITY with the symbol, actual table name, distinct raw row count, extra duplicate multiplicity and malformed count. No raw financial fields are displayed. These lines are emitted only after successful ledger integrity verification. Any observed duplicates in a different financial table remain BLOCKED. The previous Capital diagnosis demonstrated Capital itself has zero extra identical raw rows.

## One planned owner-side validation

A guarded one-line PowerShell command will fetch the pinned runner run-finance-five-capital-variant-pilot-once.ps1 and execute 162 tests (old 142 owner-passed + one new five-pilot table-attribution test + 19 new Capital compatibility tests). If all pass, it makes ONLY ONE existing-cache QMT worker call for five stocks, including 002188, and records the revised review-only/quarantined results. It requires the old ledger SHA256 (4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1), idle task, existing runner mutex, and protection of Beijing 18:30-23:35.

If the 20:05 scheduled task legitimately advances the ledger, stop and do NOT reset, backdate or rewrite source state.

## No approval or deployment

No data import, Parquet/pin edits, QMT downloads, pending changes, new scheduler or GitHub Actions. The implementation is a diagnostic PREVIEW, not a recovery writer. Production PR #243 and the scheduled daily task are unchanged. A future actual writer still requires explicit case-specific human authorization, immutable source version retention, staged Arrow validation, CAS ledger/pins, multi-table crash journal, rollback and post-commit verification.

Passing a test or preview means only evidence sufficient for further MANUAL REVIEW.
