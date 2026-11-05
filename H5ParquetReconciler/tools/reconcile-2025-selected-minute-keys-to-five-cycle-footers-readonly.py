#!/usr/bin/env python3
"""2025 purchased source-only annual five-minute-cycle/footer reconciliation.

Verify and REUSE all twelve accepted purchased 1min/5min stockday-grid
checkpoints. Read original five-minute-cycle Parquet FOOTERS only and compare
aggregate stockday-equivalents. No symbol/ts column batches, no H5 bars,
no OHLCVA, no new index or market file. Unselected source records are UNKNOWN
(unclassified), NOT automatically missing or non-A-share records.

The exact multiple of grid sizes is a conservation property of total rows,
not proof that unselected records form individually complete stockdays.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CYCLES = {"1min": 241, "5min": 48, "15min": 16, "30min": 8, "60min": 4}


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _load("annual_2025_verified_minute_checkpoints",
          "run-purchased-2025-minute-grid-checkpoint-batch.py")
F = _load("annual_2025_footer_only_source_inventory",
          "inventory-parquet-primary-footers.py")


def reconcile(root, *, max_source_files=500, max_rowgroups=100000):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Untrusted purchased source root")
    if (type(max_source_files) is not int or not 1 <= max_source_files <= 10000
            or type(max_rowgroups) is not int or not 1 <= max_rowgroups <= 1000000):
        raise ValueError("Invalid footer-only scan budgets")
    signature = B.A.I.N.source_snapshot(root, 2025)
    month_audits = {}
    for month in B.months("2025-01", "2025-12"):
        checkpoint = B.verified_receipt(month, root, signature)
        if checkpoint is None:
            raise ValueError("Missing completed 2025 month source-grid receipt: " + month)
        month_audits[month] = checkpoint
    purchased_count = {
        p: sum(a["periods"][p]["keys"] for a in month_audits.values())
        for p in ("1min", "5min")
    }
    purchased_stockdays = {
        p: sum(a["periods"][p]["stockdays"] for a in month_audits.values())
        for p in ("1min", "5min")
    }
    if purchased_stockdays["1min"] != purchased_stockdays["5min"]:
        raise ValueError("Verified 2025 purchased 1m/5m stockday counts differ")
    if any(purchased_count[p] != n * purchased_stockdays[p]
           for p, n in (("1min", 241), ("5min", 48))):
        raise ValueError("Verified purchased 2025 grid conservation broken")
    discovered, naming = F.source_files(
        root, tuple(CYCLES), 2025, 2025)
    total = sum(len(discovered[p][2025]) for p in CYCLES)
    if total == 0 or total > max_source_files:
        raise ValueError("Untrusted/overbudget original 2025 source footer files")
    footer_rows = {}
    for p in CYCLES:
        paths = discovered[p][2025]
        if not paths:
            raise ValueError("Missing source year 2025 period " + p)
        foot = F.year_period_footer(
            root.resolve(), paths, 2025, p, max_rowgroups)
        if (foot["row_groups"] <= 0
                or foot["nonempty_row_groups_without_usable_ts_bounds"] != 0
                or foot["row_groups_with_any_ts_bounds_outside_named_year"] != 0
                or not foot["footer_envelope_complete_for_nonempty_row_groups"]):
            raise ValueError("Untrusted 2025 source timestamp footer envelope: " + p)
        footer_rows[p] = foot["source_rows_from_parquet_footers"]
    if any(footer_rows[p] % CYCLES[p] for p in CYCLES):
        raise ValueError("One or more five-cycle 2025 source footer row totals are not standard-grid multiples")
    equivalents = {p: footer_rows[p] // CYCLES[p] for p in CYCLES}
    if len(set(equivalents.values())) != 1:
        raise ValueError("Five-cycle 2025 source footer stockday-equivalent totals disagree")
    if (purchased_count["1min"] > footer_rows["1min"]
            or purchased_count["5min"] > footer_rows["5min"]):
        raise ValueError("Verified selected A-share keys exceed whole-source footer rows")
    unselected = {
        p: footer_rows[p] - purchased_count[p]
        for p in ("1min", "5min")
    }
    if (unselected["1min"] % 241 or unselected["5min"] % 48
            or unselected["1min"] // 241 != unselected["5min"] // 48):
        raise ValueError("Unselected 2025 source counts do not conserve across minute cycles")
    unselected_equivalent = unselected["1min"] // 241
    if equivalents["1min"] != (
            purchased_stockdays["1min"] + unselected_equivalent):
        raise ValueError("2025 selected-plus-unselected source conservation mismatch")
    if B.A.I.N.source_snapshot(root, 2025) != signature:
        raise RuntimeError("Original source metadata drifted during annual 2025 reconciliation")
    return {
        "format": "AStockDataTools 2025 purchased source footer versus exact A-share key audit v1",
        "status": "2025_source_footer_and_selected_ashare_key_totals_exactly_conserved",
        "verified_2025_grid_months": list(month_audits),
        "selected_ashare_stockdays": purchased_stockdays["1min"],
        "selected_ashare_minute_keys": purchased_count,
        "whole_source_footer_rows": footer_rows,
        "whole_source_standard_stockday_equivalents_by_cycle": equivalents,
        "unselected_source_rows_unknown_security_class": unselected,
        "unselected_source_standard_grid_equivalents_not_certified_stockdays":
            unselected_equivalent,
        "unselected_source_includes_unverified_nonashare_or_unrecognized_codes_possible": True,
        "unselected_source_security_categories_classified": False,
        "unselected_source_individual_stockday_grid_certified": False,
        "further_source_symbol_classification_requires_separate_key_only_audit": True,
        "footer_timestamp_envelopes_are_not_individual_stockday_certification": True,
        "independent_exchange_calendar_certified": False,
        "purchased_source_unit_and_corporate_actions_certified": False,
        "purchased_source_content_sha_certified": False,
        "original_market_files_modified": False,
        "purchased_ohlcva_bars_opened_or_copied": False,
        "new_private_index_or_market_files_written": False,
        "h5_opened_for_bars": False,
        "production_source_activated": False,
        "yearly_source_file_count": total,
        "naming_ambiguity_caveats": naming,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--max-source-files", type=int, default=500)
    ap.add_argument("--max-rowgroups", type=int, default=100000)
    args = ap.parse_args(argv)
    result = reconcile(
        args.root, max_source_files=args.max_source_files,
        max_rowgroups=args.max_rowgroups)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
