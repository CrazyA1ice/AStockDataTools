# 2025 SZ302 source exception: issuer-confirmed 300114 -> 302132 (2026-11-05)

## Live 2025 source prefix audit already passed
- Purchased source original five-minute rows: **64,081,920**; current A-share code-pattern selected 63,200,928; excluded 880,992.
- All excluded stockdays 48/48. Unselected prefixes: SH900=41 securities / 9,921 stockdays / 476,208 bars; SZ200=37 securities / 8,190 stockdays / 393,120 bars; **SZ302=1 security / 243 stockdays / 11,664 bars**.
- SH900 and SZ200 have strong B-share code-pattern interpretation, but require independent master evidence before wholesale production category registration. **SZ302 requires special attention**: it may include a regular listed A share that the current `CORE.is_a_share_candidate` prefix rule excludes (SZ prefixes 000/001/002/003/300/301 only).

## Authoritative external issuer code-change evidence
- Official issuer announcement (company's disclosure hosted at Shenzhen Stock Exchange):
  https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF
- Issuer: 中航成飞; **former 300114 (中航电测) -> new 302132 (中航成飞)**, effective **2025-02-17**. Existing listed corporate entity continued. Exchange index adjustment 2025-06-03 also lists 302132 中航成飞 in Shenzhen 100 constituents:
  https://investor.szse.cn/disclosure/notice/general/t20250603_613877.html
- **The current dataset output gives only the prefix SZ302, not its exact six-digit code or date range. The exact source symbol must be read before asserting it is 302132.**
- If the original 2025 purchased data contains `SZ302132` before 2025-02-17, vendor historical renaming/rekeying is possible. Historical source-key semantics would then differ from contemporaneous exchange code labels. Never silently relabel data or collapse duplicate keys into one date.

## Newly committed, still pending Windows test
- `tools/audit-purchased-2025-302132-code-transition-readonly.py` streams only source `ts,symbol` from 2025 bought 5min; audits all `SZ302*` observed raw aliases plus historical/new target codes `SZ300114` and `SZ302132`.
- The tool checks source 2025 footer row totals and reuses 12 validated source-key checkpoint receipts, separately tests official effective date, prints raw public security-code spellings, stockdays/bars/date min/max and before/after effective counts, and checks all target 48-bar time grids.
- No price/volume/amount read, no source-market edits, no H5 bars, no new minute indexes and no production activation.
- `tests/test_audit_purchased_2025_302132_code_transition_readonly.py` adds 7 synthetic tests; `run-purchased-2025-302132-code-transition-audit.ps1` is Windows run gate.
- **Do not modify the globally consumed A-share candidate predicate yet.** It is used by already verified 1m/5m private indexes; unilateral expansion would invalidate signatures/coverage comparisons and could imply false historical exchange code labels. After observing exact original source timeline, design an explicit effective-dated alias/equity-class exception and a versioned index migration or research-only route, then verify historical unmodified source against authoritative evidence.

## Other open issues
- The original unselected 1min rows 4,423,314 have not been independently audited by security-code/date; five-minute code classification alone is not full 1min equality proof.
- 2025 official exchange-day calendar is not independently reconciled, vendor OHLCVA units and adjustments not fully certified.
- 22,274 private H5 daily-source candidate rows are SHA/schema/key verified but not yet merged into production; daily research overlay integration remains a separate gate.
