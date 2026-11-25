# 002188.SZ Top10Holder: exact raw-row multiplicity provenance, P4

Status: **source-controlled read-only audit ONLY**. New offline tests and targeted real-cache audit are not yet Windows owner-verified. This branch stacks on Draft PR #248, whose 162/162 tests and five-symbol QMT cache-only pilot passed on the user's computer.

## Why this follow-up is required

The owner's QMT run confirms 4/5 symbols reached manual-review-only, while 002188.SZ was BLOCKED. The precise originating table for that stock was identified:

- Symbol: 002188.SZ; problematic historical source table: **Top10Holder**, not Capital.
- Historical Counter union: **779 distinct raw JSON records + 9 extra identical-raw occurrences** (total 788).
- Number of different duplicate raw record hashes and which snapshot days contain them are NOT yet known.
- The independently checked Capital table had **108 historical report keys / 109 current report keys**, with **one new 20261119 key**, two immutable m_quarter variants, and zero exact raw Capital duplicates. No economic-field conflict or missing Capital report key was observed.
- This proves why simply changing the Capital filter would be unsafe: the nine-table importer must also preserve the Top10Holder raw multiplicity.

The four other symbols remain evidence-only (original SHA hashes pinned in finance-five-pilot-review-evidence-20261125.json), including 002328's unresolved issuer-verified 57896 versus QMT 57900 quantitative discrepancy. All five remain pending in production. No automation or review-output status constitutes data approval.

## Target diagnostic: one cache-only QMT read, no write

The new script qmt_finance_top10holder_duplicate_audit_once.py:

1. Refuses the run unless the pending ledger is exactly the verified 2026-11-24 epoch SHA256 4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1, with 54 pending, 002188.SZ SOURCE_HISTORY_CONFLICT table=Capital and 688259.SH CACHE_DECODE_ERROR. A later legitimate daily task must cause STOP, not a reset.
2. Requests exactly **002188.SZ**, mode=cache, with the project's existing read-only worker; all nine tables must be present. It does not call a download API.
3. Enumerates the existing Top10Holder immutable snapshots for each date, resolves the verified active selection via production E._financial_snapshot_file, validates the source payload with E._financial_snapshot_rows (Arrow schema/row identity/Parquet SHA), and checks selected file bytes did not change during read.
4. Reconstructs a Counter union using elementwise **MAX**, not sum across days, and checks exact equality with production F._prior_rows. It refuses a divergent union or invalid filename.
5. For every raw JSON row with historical multiplicity greater than one, emits only its **SHA256**, endDate, MAX historical occurrence count, each selected asof's count, number of distinct snapshot position indices, and the exact count in current QMT cache. Snapshot index positions are **not independent evidence of distinct economic shareholders**.
6. Emits summary counts for full historic/current raw row differences and whether the previous 779+9 observation remains reproducible. No raw shareholder names, economic amounts or source row JSON are printed.
7. Buffers all row and snapshot evidence until after a final ledger hash comparison succeeds. A ledger drift or source reconciliation failure never publishes successful forensic conclusions.
8. Every output has allow_deduplication=false, allow_apply=false, allow_pending_clear=false; old snapshots and active pins remain untouched.

## Remaining manual decisions after reading the evidence

- If duplicate rows occur **within** one selected Top10Holder snapshot, determine whether source rows represent distinct shareholders with identical disclosed attributes, duplicated provider export records or another provider-specific semantic. There is no automatic answer simply from equal JSON payloads. Retain all occurrences until provenance is independently established.
- If the raw row repeats once on **different days**, this is normal historical observation; the MAX union must not increase the count. Tests specifically cover this.
- If QMT currently returns fewer occurrences than the selected old snapshot, report the multiplicity loss but do not replace or deduplicate historical snapshots.
- Any future specific-row acceptance requires exact pinned hashes, human approval, immutable old/new versions and separate CAS and crash-safe recovery writer. This PR does not implement or authorize that writer.

## Validation plan

The one-command, Git-blob pinned Windows PowerShell runner checks canonical deployed production script hashes and HEAD, protected Beijing 18:30–23:35 interval, existing scheduled-task idle state and existing Local\AStockDataTools2005AllStages mutex. It stages audited files in TEMP, runs **181** offline unit tests (162 previously owner-passed + 19 new synthetic tests), and only then performs one single-symbol QMT cache-only read. It verifies the original pending ledger SHA256 before and after and removes its temporary staging directory.

Expected completion lines include FINANCE_OFFLINE_181_TESTS_PASS, DUPLICATE_AUDIT_LEDGER_UNCHANGED_VERIFIED, one or more DUPLICATE_AUDIT_ROW_PROVENANCE, DUPLICATE_AUDIT_SUMMARY and DUPLICATE_AUDIT_COMPLETE_NO_DEPLOY. The runner does not require repeating the old 53-stock audit or five-stock cohort scan.

### Safety constraints

No automatic deduplication, no QMT downloads, no Parquet changes, no ledger clearing, no active pin edits, no production importer changes, no extra scheduler, no GitHub Actions. The PR must remain Draft until the owner-run test receipt and actual provenance output are reviewed. Independent approval is required for all data changes.
