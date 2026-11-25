# P6 — Five-symbol evidence freeze and case-by-case human adjudication

**Status:** source-controlled historical evidence freeze, one offline-only pure validator and 41 tests, Draft PR, NO LIVE MUTATIONS, NO approvals. This P6 freezes results proven by the owner's Windows runs in earlier Draft PR #248 and #250; these were performed against the **2026-11-24 ledger epoch**. This packet is not a fresh check of the private live source. Do not substitute it for a future active-state CAS and full nine-table revalidation.

## Verified evidence timeline

- PR #248 owner run: 162/162 offline tests pass and existing QMT cache 5/5. 002178, 002310, 002328, 002388 were REVIEW_REQUIRED; 002188 remained blocked by historical Top10Holder duplicates.
- PR #249 owner run: 181/181 offline tests pass and one cache-only QMT read for 002188. Old Top10Holder selected 2026-11-17 snapshot 779/779, 2026-11-18 snapshot 788 rows/779 distinct, nine extra identical raw occurrences; current QMT cache also 788/779, full historical/current Counter(MAX) equality, unchanged ledger and unchanged two selected snapshot SHA256 fingerprints.
- PR #250 owner run: 222/222 offline tests pass and one cache-only QMT read for 002188. Capital becomes CAPITAL_ADDITIVE_REVIEW_REQUIRED, prior 108 -> current 109 report keys, one new **string** report key 20261119 (canonical JSON token including surrounding quotes), original 110 Capital raw variants, no removed keys and no shared economic field change. Nine Top10Holder raw SHA256 groups with count exactly two each are preserved and the full 779-distinct / 788-total Counter matches cache exactly. PR #250 preview digest 426ffd9ad947bf320625f337e59b3e21baa47fd196fe6a3e1403a40536e0a25d, new record SHA256 32c01e03bb442c6de6df075e735bcddf4e669061a626bccf491e798a1d7251cb.
- Every live read above completed without import, approval, Parquet mutation or pending clear. Reported ledger SHA256 4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1. Previous 002188 block is **retained in the PR #248 source artifact**; PR #250 later review supersedes it for the audited historical observation, but never rewrites the historical record.

## Manual adjudication matrix — all default HOLD_PENDING

| Symbol / Target | Source validation status | Independent issue requiring an actual decision before any apply | Current decision |
| --- | --- | --- | --- |
| 002178.SZ / Top10Holder | ISSUER_DISPUTED_REVIEW_REQUIRED | The previous/current holder name differs by a space; provider type QFII机构 vs 公司 and issuer type 境外法人 are taxonomically inconsistent; the issuer source only confirms name, NOT type equivalence | **HOLD_PENDING** |
| 002188.SZ / Capital | CAPITAL_ADDITIVE_REVIEW_REQUIRED | One new 20261119 report key (QMT string), exact no-economic-drift Capital checks pass. The 9 identical raw Top10Holder groups cannot yet be interpreted as independent beneficial owners or harmless exporter duplicates, even though exact source multiplicity is preserved | **HOLD_PENDING** |
| 002310.SZ / Top10Holder | ISSUER_DISPUTED_REVIEW_REQUIRED | Punctuation discrepancy in holder name (ASCII hyphen vs Chinese 一) and issuer disclosure mismatch; cross-table Capital m_quarter raw-version variants are preserved but do not resolve source identity | **HOLD_PENDING** |
| 002328.SZ / HolderNum | ISSUER_DISPUTED_REVIEW_REQUIRED | Issuer report shows 57,896, QMT current 57,900 for 20260930; shareholderA semantics not independently proven. Do not treat 4-person difference as benign rounding or silently replace the issuer-confirmed historical version | **HOLD_PENDING** |
| 002388.SZ / Top10FlowHolder | HOLDER_METADATA_REVIEW_REQUIRED | Source declareDate/type metadata changes and Capital m_quarter-only version histories have been checked in read-only preview; case-specific metadata provenance/intent still requires a human decision | **HOLD_PENDING** |

Important: the five REVIEW_REQUIRED classifications mean only that **the specified versioned repair proposal can be constructed without dropping historical raw records according to its scoped checks**. They are not issuer-verification truth, approval, deployment permission, pending clearance, or proof that today's QMT/ledger is unchanged.

### Evidence artifacts

- finance-five-review-freeze-20261125.json — **frozen final five-case human HOLD decisions**, one preview hash per case, original unresolved issue codes, original ledger and source-stage receipts; explicitly five review-only / zero approved, and every data-write/auto-clear/dedup flag false.
- finance-five-pilot-review-evidence-20261125.json — original four review cases + 002188's former blocked outcome, retained unmodified to preserve provenance.
- finance-priority-three-adjudication-manifest-20261125.json — three issuer-documented holder disputes and exact historical/current row hashes, including 002328's original/current numeric values.
- finance-002188-top10holder-raw-multiplicity-pin-20261125.json — exact nine repeated raw SHA256 fingerprints, report period 20200930, original selected snapshot filenames/full-file hashes and Counter(MAX) union; no dedup flags.

P6 validator finance_five_review_freeze_once.py checks all four JSON sources, the fixed 5-case scope, both stages of owner evidence, identical source ledger epoch, all five review hashes, exact 002188 nine-row fingerprints and snapshot hashes, three issuer dispute states, 002328 original 57896 vs 57900 mismatch, and literal false approval/write/clear flags. It only returns a deterministic hashed **historical decision packet**. It does not access QMT, production ledger, Parquet or external URLs. Review packet printing occurs *after* all checks, so malformed source evidence never produces a fake valid receipt.

The P6 Windows PowerShell runner stages six reviewed Git blobs to TEMP, runs **41 new offline tests**, and validates the frozen packet. It does not re-run 222 old tests or any previous QMT scan, does not touch the 20:05 task, and does not require the ledger still be at the audited hash (which could have legitimately advanced). A successful packet still states live_source_revalidation_complete=false, eligible_to_apply=false and human_approved=0. If Git production HEAD has changed, it refuses the pinned command rather than switching production branch.

## Future writer admission design — NOT IMPLEMENTED IN P6

Before any concrete write the operator must explicitly approve **one case at a time** with exact symbol/table, intended source version, evidence fingerprints, why the discrepancy is acceptable or which issuer value should take precedence, date of approval, and a recovery/rollback scope. A REVIEW_REQUIRED flag alone never satisfies this.

A separately reviewed writer PR would still require:
1. **Fresh live-state preflight:** 20:05 scheduled task Ready, shared mutex held, protected 18:30–23:35 Beijing period excluded; detect another runner. Rehash canonical production scripts/HEAD and read the **current** ledger; never force the old 2026-11-24 epoch or reset the task cursor.
2. **Complete source revalidation:** read all nine QMT financial tables in existing-cache mode, verify all selected immutable historical snapshots, active pin identities and original SHA256. Exact Capital string report-key and Top10Holder multiplicity constraints must still hold, and 688259.SH remains quarantined.
3. **One-case mutation intent:** a distinct, explicit approval document naming the expected old/new raw record hashes; no all-five wildcard, no generic allowance, no auto-dedup. For 002328, independent issuer/provider count discrepancy remains unresolved by P6 and must not be accidentally approved by a generic metadata rule.
4. **Non-destructive staged candidate:** stage a new immutable version in private TEMP, verify Arrow schema, symbols, asof, row identity, all source counts and file fingerprints. Retain all original snapshots and source duplicates; do not normalize m_quarter or any holder fields without separately approved source semantics.
5. **Crash-consistent transition:** durable per-case journal and idempotent staged-to-immutable promotion, explicit active-pin and pending-ledger compare-and-swap against their freshly read old content hashes, protected rollback/recovery procedure and post-commit readback of all nine tables. On failure do not mark pending complete; never silently swallow partial repairs.
6. **Auditable completion:** append a bounded evidence receipt with old/new hashes, approval reference, counts, nine-table verification and post-commit live ledger, without exposing raw shareholder names. Complete only after all validation, not merely a successful Parquet write.

The only person operating this repository can make the explicit final decision; P6 does not assume two-person sign-off or external approval tooling. **No case has been signed off yet.**

## Invariants

Do not touch active Parquet, QMT cached data, historical selected snapshots, live financial pending ledger (54 entries as last observed), production importer, PR #243, 20:05 scheduled Windows task or add GitHub Actions. PR #251 should remain Draft. The offline packet is a research/decision artifact and must never be reinterpreted as a production command. If the scheduled task has naturally advanced the ledger, retain its new state and plan a new proof rather than reverting anything.
