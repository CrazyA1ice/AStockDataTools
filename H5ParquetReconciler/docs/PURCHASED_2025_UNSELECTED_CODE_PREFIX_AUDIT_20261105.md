# 2025 purchased Parquet unselected code-prefix inspection (2026-11-05)

## Confirmed previous Windows acceptance
- All 12 calendar months of purchased 2025 A-share 1min/5min source-key indexes validated; **1,316,686** observed purchased A-share stockdays; 1min **317,321,326** and 5min **63,200,928** matching exact regular grids.
- Five purchased original period **footer** totals: 1min 321,744,640; 5min 64,081,920; 15min 21,360,640; 30min 10,680,320; 60min 5,340,160. Their standard-grid equivalents are each 1,335,040.
- Raw rows outside current A-share code filter: 1min **4,423,314**; 5min **880,992**; both / 241 or 48 = **18,354 THEORETICAL grid equivalents**.
- This difference is aggregate and **cannot yet be called 18,354 actual stockdays**, non-A-share securities, ETFs or exchange-data gaps.

## This branch's next read-only gate
- `tools/audit-purchased-2025-unselected-5min-code-prefixes-readonly.py` revalidates **all 12** source-key receipts and the five original footer totals before scanning original **5min Parquet ts/symbol ONLY**, capped at **70 million rows**; previously accepted 2025 5min footer count is **64,081,920**.
- Filter uses the **same** `CORE.symbol_id(raw)` and `CORE.is_a_share_candidate(canonical,2025)` as the purchased key-index builder. Aggregate accepted rows must equal **63,200,928**, and remaining rows **880,992**, or it fails closed.
- Each unselected record is grouped by canonical venue and first three numeric code digits, or **UNRECOGNIZED**. These are **raw code prefixes, NOT certified security asset types**. No full raw stock IDs, price/volume/amount data or row timestamps are exported.
- Separately check observed excluded (raw_symbol,calendar_day) 5min membership bits against exactly 48 legal session time keys. Any duplicate source key is an error; anomalous time-grid stockdays are printed in aggregate and the command exits failure. The measured number of observed stockdays will tell us whether the 18,354 theoretical equivalents correspond to actual complete source stockdays. The 1min residual is still **footer-only** and its security categories are NOT assumed to equal the 5min categories.
- Source sizes/mtimes and the 2025 vendor/source signature are checked for drift. No H5 market-data read, new source-key index, private Parquet, paid bar copy, report file, stockday fill or production activation.
- Synthetic regression: `tests/test_audit_purchased_2025_unselected_5min_code_prefixes_readonly.py` (8 tests). Native Windows one-line entry: `run-purchased-2025-unselected-5min-code-prefixes-audit.ps1`. The new code has not yet passed the user's Windows run.

## Later
- If source unselected 5min grids pass, separately review **individual code prefixes** with authoritative securities-master evidence (codes can change class over time). Only then decide whether to widen A-share candidate selection, modify query coverage or quarantine class-specific records.
- Optionally perform a separately bounded 1min source-only code-prefix independent cross-check without scanning purchased OHLCVA.
- Independent 2025 exchange calendar and 22,274 historical day H5-candidate research-only overlay remain separate stage gates. Do not use source-code prefixes to trigger any H5 market writes.
