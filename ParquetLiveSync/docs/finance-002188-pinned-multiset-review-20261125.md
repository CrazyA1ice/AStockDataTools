# P5: 002188.SZ pinned Top10Holder multiplicity and Capital additive preview

Status: IMPLEMENTED AS READ-ONLY CODE ONLY, NOT OWNER-TESTED, NOT DEPLOYED. This Draft branch stacks on PR #249. The 2026-11-25 13:06 Beijing owner run passed 181/181 offline tests and a single existing-cache-only 002188.SZ audit. The pinned 2026-11-24 pending ledger SHA256 is 4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1.

## Selected immutable snapshots and QMT provenance

| As-of | Active selected snapshot | SHA256 | Rows | Distinct | Extra raw occurrences |
| --- | --- | --- | ---: | ---: | ---: |
| 2026-11-17 | 2026-11-17-060479650601cca4.parquet | a596176479eb6c99716e6cb56e8cb50bad5885dcf9ea54a818a0992227870113 | 779 | 779 | 0 |
| 2026-11-18 | 2026-11-18-6728bc156bde7c85.parquet | ebab890780d46e20dc1d7eaa239bda66e7b8a00c2f119229bba41565e905ba9a | 788 | 779 | 9 |

Nine distinct raw Top10Holder records for reporting period 20200930 have count exactly two in the later selected snapshot and in the current QMT cache. All other records have count exactly one. The Counter(MAX) historical union has 779 distinct raw strings and total multiplicity 788; full historical/current multiset equality was verified in the previous audit (zero lost, zero added, counting duplicates). Full historical union SHA256:

664618c29fbdc510fc2155c0657a8cb8c843be45c0e5bfa2affa68f364756359

All nine exact original raw-record SHA256 values are source-pinned in the implementation AND the separate evidence JSON manifest, finance-002188-top10holder-raw-multiplicity-pin-20261125.json. Neither a repeated raw payload nor different row positions proves separate beneficial-owner identities. No auto-deduplication or owner identity assumption.

Capital was independently audited: 108 historical report keys -> 109 current keys; only new m_timetag key 20261119; two historical m_quarter variants, 110 historical raw variants and zero observed shared-key economic changes or old missing report keys. The new implementation must revalidate these exact constraints from the currently supplied read-only QMT cache.

## Fail-closed review rules

- Pure versioned recovery preview is scoped ONLY to symbol 002188.SZ, mode CAPITAL_ADDITIVE, target table Capital, and a repeated historical Top10Holder Counter. All other symbol/table/mode combinations retain their original strict raw-record count=1 rule.
- Every raw record remains in the historical Counter with its original count. Exactly 779 distinct, 788 total, nine repeated raw SHA256 entries each count=2, all other entries count=1. Full Counter digest must match. No global normalization or unique-by-row deduplication.
- Every repeated row has endDate=20200930. Current Top10Holder cache must contain exactly the SAME full raw Counter including multiplicities. A single missing or extra occurrence BLOCKS.
- Both selected immutable Top10Holder snapshot filenames, asof dates, SHA256, row counts and distinct/extra counts must exactly match the pinned 2026-11-17/18 evidence. The runtime verifies these using the production selected snapshot reader and recomputes the Counter(MAX) union, then compares the result with authoritative F._prior_rows. An extra snapshot asof, changed active pin, corrupted Parquet, SHA drift or mismatched union BLOCKS.
- Capital additive validation retains all older raw historical variants and demands 108 -> 109 report keys, exactly one new key 20261119, zero removed report keys and complete economic-field equality for each shared report key. No rounding, waiver or provider field suppression beyond existing m_quarter semantics.
- Other eight tables are still validated by the nine-table historical protections. No other financial table may contain repeated raw history and qualify for this special exception.
- The pending ledger epoch is fixed to 2026-11-24, 54 pending, SHA256 4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1. The 688259.SH known provider UTF-8 error remains quarantined and is never queried.
- The preview is ALWAYS REVIEW_ONLY_NO_APPLY_AUTHORIZATION. No pending clearance, Parquet write, active-pin update or deduplication is permitted. This only records evidence for future independent human decision.

## Single-run diagnostic and tests

New read-only one-stock driver qmt_finance_002188_pinned_review_once.py validates the ledger, all exact snapshot pins and the evidence manifest BEFORE its one QMT cache-only read. It collects all nine verified histories, invokes the pure pinned preview and buffers results until the final ledger hash verification. Outputs only source fingerprints and Capital report-key counts, never shareholder names or raw records.

New tests/test_finance_002188_exact_multiplicity_review.py contains 27 synthetic offline tests for exact raw multiplicity preservation; SHA mismatch; historical snapshot content/selection change; QMT missing/extra duplicates; non-scope rejection; report period drift; full end-to-end 779+9 holder multiset and 108+1 Capital additive scenario; and ledger change suppressing output.

New PowerShell 5.1 runner run-finance-002188-pinned-review-once.ps1 stages reviewed Git blobs, verifies file hashes and canonical production HEAD, requires idle 20:05 scheduled task plus the shared runner mutex, protects Beijing 18:30-23:35, runs 208 offline tests (previous 181 owner-passed + new 27), and ONLY THEN performs one 002188.SZ existing QMT cache read. It verifies the same original ledger SHA256 before/after. No GitHub Actions.

## Unresolved and prohibited

This is NOT a recovery writer or permission to accept the source. Future actual snapshot creation or ledger clearance requires independent human review per original-record SHA256, immutable staged Parquet files, CAS ledger and active pins, crash journal, rollback and post-write verification. Previous four other review-only symbols remain pending; 002328.SZ issuer's 57896 versus QMT 57900 discrepancy remains separately unresolved. No changes to production importer, scheduler, PR #243, source ledger or any raw data.

New 27 tests and one-stock real-cache P5 pilot have NOT yet been confirmed by owner. The PR remains Draft. If the ledger advanced legitimately, STOP before QMT rather than resetting state.
