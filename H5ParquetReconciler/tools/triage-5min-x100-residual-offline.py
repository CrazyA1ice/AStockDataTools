#!/usr/bin/env python3
"""Offline read-only residual attribution from a previous 5min ×100 audit JSON.

Derives *provable* overlaps/bounds from marginal price/amount/volume counts.
Never fabricates a full three-field Venn diagram from non-identifying totals.
No H5/Parquet data is read. An old report with incomplete/invalid counters
fails closed instead of turning a partial audit into a verified conclusion.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "residual_triage_core", HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def integer(value, label, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Invalid nonnegative integer {label}: {value!r}")
    return value


def measure(part, key):
    # Absent per-prefix/per-day count means 0 for counter-like source schema.
    return integer(part.get(key, 0), key)


def intersect_min(a, b, union_size):
    """Inclusion–exclusion lower bound for any pair inside the same union."""
    return max(0, a + b - union_size)


def bounds_for_group(rows, total_extra):
    """Constrain group union sizes without assuming unknown field overlaps.

    Each residual union contains all V rows. Additional rows must be in A or
    P but not V; local minimum = max(0, max(A,P) - V). Mandatory increments
    in OTHER disjoint groups further bound this group's possible increments.
    """
    mandatory = {
        k: max(0, max(row["amount"], row["price"]) - row["volume"])
        for k, row in rows.items()
    }
    floor_sum = sum(mandatory.values())
    if floor_sum > total_extra:
        raise ValueError("Marginals require more non-volume-only rows than union permits")
    out = {}
    for name, row in rows.items():
        others_min = floor_sum - mandatory[name]
        max_extra = min(
            row["amount"] + row["price"],
            row["matched"] - row["volume"],
            total_extra - others_min,
        )
        if max_extra < mandatory[name]:
            raise ValueError("No feasible field overlap in " + name)
        out[name] = {
            "matched_keys": row["matched"],
            "candidate_volume_mismatch": row["volume"],
            "amount_mismatch": row["amount"],
            "price_mismatch": row["price"],
            "candidate_any_mismatch_lower_bound": row["volume"] + mandatory[name],
            "candidate_any_mismatch_upper_bound": row["volume"] + max_extra,
            "nonvolume_only_lower_bound": mandatory[name],
            "nonvolume_only_upper_bound": max_extra,
            "candidate_volume_mismatch_pct_of_matched": (
                round(100 * row["volume"] / row["matched"], 5)
                if row["matched"] else None),
            "breakdown_is_exact": False,
        }
    return out


def validated_rows(original, key, compared, amount, price, volume):
    part = original.get(key)
    if not isinstance(part, dict) or not part:
        raise ValueError(f"Missing {key} source breakdown")
    result = {}
    for name, counters in part.items():
        if not isinstance(counters, dict):
            raise ValueError(f"Missing counters in {key}/{name}")
        n = measure(counters, "matched")
        v = measure(counters, "candidate_h5_volume_x100_mismatch")
        a = measure(counters, "amount_mismatch")
        p = measure(counters, "price_mismatch")
        if max(v, a, p) > n:
            raise ValueError(f"Marginal count exceeds matches for {key}/{name}")
        result[name] = {"matched": n, "volume": v, "amount": a, "price": p}
    for field, expected in (
        ("matched", compared), ("volume", volume),
        ("amount", amount), ("price", price)
    ):
        actual = sum(row[field] for row in result.values())
        if actual != expected:
            raise ValueError(f"Nonconserving {key} {field}: {actual} vs {expected}")
    return result



MASK_NAMES = (
    "none", "volume", "amount", "price", "volume_amount",
    "volume_price", "amount_price", "volume_amount_price"
)


def select_five_minute_result(report):
    """Select a single bounded 5min section; validate any day companion.

    This accepts historical 5min-only reports and newer one-window day+5min
    reports without touching raw H5/PQ. Multiple years/extra cycles fail closed.
    """
    results = report.get("results")
    if not isinstance(results, dict) or len(results) not in (1, 2):
        raise ValueError("Require one 5min result or one matched day+5min window")
    names = [key for key, obj in results.items()
             if isinstance(obj, dict) and obj.get("period") == "5min"]
    if len(names) != 1:
        raise ValueError("Require exactly one bounded 5min audit result")
    label = names[0]
    result = results[label]
    year = integer(result.get("year"), "five minute year", minimum=2000)
    if label != f"5min/{year}":
        raise ValueError("5min label/year mismatch")
    companion = False
    if len(results) == 2:
        companion_name = f"day/{year}"
        d = results.get(companion_name)
        if (not isinstance(d, dict) or d.get("period") != "day" or
                d.get("year") != year or d.get("scan_complete") is not True or
                d.get("issues") != [] or
                d.get("safe_to_automatically_union") is not False or
                d.get("from_date") != result.get("from_date") or
                d.get("to_date") != result.get("to_date") or
                d.get("universe_mode") != result.get("universe_mode")):
            raise ValueError("Companion day section must be a complete matching bounded window")
        companion = True
    if report.get("requested_years") is not None and report["requested_years"] != [year]:
        raise ValueError("Audit request year must equal selected 5min year")
    if report.get("requested_periods") is not None and set(
            report["requested_periods"]) != ({"day", "5min"} if companion else {"5min"}):
        raise ValueError("Audit requested cycles do not match selected evidence")
    return label, result, companion


def _validated_mask_group(raw, matched, volume, amount, price, any_diff=None):
    if not isinstance(raw, dict) or set(raw) != set(MASK_NAMES):
        raise ValueError("Exact residual masks must contain all eight disjoint classes")
    out = {name: integer(raw[name], "exact residual mask " + name)
           for name in MASK_NAMES}
    if sum(out.values()) != matched:
        raise ValueError("Exact residual masks do not conserve matched row count")
    for field, expected in (
            ("volume", volume), ("amount", amount), ("price", price)):
        got = sum(n for key, n in out.items() if field in key.split("_"))
        if got != expected:
            raise ValueError("Exact residual masks disagree with " + field + " marginal")
    if any_diff is not None and matched - out["none"] != any_diff:
        raise ValueError("Exact residual masks disagree with total residual")
    return out


def exact_masks_if_present(candidate, by_prefix, by_day,
                           matched, volume, amount, price, any_diff):
    """Prove optional existing exact masks from all marginals; never infer overlaps."""
    global_mask = candidate.get("exact_residual_field_mask_counts")
    prefix_mask = candidate.get("exact_field_mask_by_prefix")
    day_mask = candidate.get("exact_field_mask_by_day")
    if all(x is None for x in (global_mask, prefix_mask, day_mask)):
        return None
    if any(x is None for x in (global_mask, prefix_mask, day_mask)):
        raise ValueError("Partial exact residual evidence; require global, by-prefix and by-day")
    validated = _validated_mask_group(
        global_mask, matched, volume, amount, price, any_diff)
    summaries = {}
    for partition, records, masks in (
            ("by_code_prefix_group", by_prefix, prefix_mask),
            ("by_day", by_day, day_mask)):
        if not isinstance(masks, dict) or set(masks) != set(records):
            raise ValueError("Exact residual mask group keys disagree: " + partition)
        details = {}
        for key, row in records.items():
            details[key] = _validated_mask_group(
                masks[key], row["matched"], row["volume"], row["amount"], row["price"])
        if any(sum(mask[k] for mask in details.values()) != validated[k]
               for k in MASK_NAMES):
            raise ValueError("Exact residual masks do not conserve across " + partition)
        summaries[partition] = details
    if candidate.get("exact_masks_are_mutually_exclusive") is not True:
        raise ValueError("Exact mask source did not affirm disjoint classes")
    return {
        "global_disjoint_field_mask_counts": validated,
        "by_code_prefix_group_disjoint_field_mask_counts":
            summaries["by_code_prefix_group"],
        "by_day_disjoint_field_mask_counts": summaries["by_day"],
        "all_field_overlap_counts_are_exact_not_estimated": True,
        "no_raw_ohlcva_or_individual_bar_keys_exported": True,
    }


def analyze(report):
    if not isinstance(report, dict) or report.get("format") != (
        "AStockDataTools H5-Parquet local coverage/difference report v1"
    ):
        raise ValueError("Expected a local H5/Parquet reconciliation JSON v1")
    if report.get("status") != "complete":
        raise ValueError("Only completed audits can be attributed")
    label, original, verified_day_companion = select_five_minute_result(report)
    if (not original.get("from_date") or not original.get("to_date")
        or original.get("scan_complete") is not True
        or original.get("issues") != []
        or original.get("safe_to_automatically_union") is not False):
        raise ValueError("Incomplete, unbounded or unsafe source audit metadata")
    q = original.get("quantity_scale_diagnostics")
    if not isinstance(q, dict):
        raise ValueError("Source has no quantity scale evidence")
    candidate = q.get("h5_volume_times_100_candidate")
    if not isinstance(candidate, dict) or candidate.get("source_values_modified") is not False:
        raise ValueError("Missing read-only ×100 candidate diagnostics")
    if candidate.get("factor_certified") is not False:
        raise ValueError("This tool is for unverified candidate mappings only")
    matched = integer(original.get("matched_keys"), "matched_keys")
    compared = integer(candidate.get("compared_overlap_keys"), "compared_overlap_keys")
    volume = integer(candidate.get("candidate_volume_mismatch"), "candidate_volume_mismatch")
    any_diff = integer(
        candidate.get("candidate_value_mismatch_with_original_price_and_amount_rules"),
        "candidate_value_mismatch")
    amount = integer(q.get("fields", {}).get("amount", {}).get(
        "different_by_existing_tolerance"), "amount_mismatch")
    price = integer(original.get("price_mismatch_rows"), "price_mismatch_rows")
    legacy = integer(candidate.get("legacy_volume_mismatch"), "legacy_volume_mismatch")
    resolved = integer(candidate.get("legacy_mismatch_resolved_by_candidate"), "resolved")
    broken = integer(candidate.get("legacy_match_broken_by_candidate"), "broken")
    if (matched != compared or
        not max(volume, amount, price, any_diff) <= matched or
        not max(volume, amount, price) <= any_diff or
        any_diff > volume + amount + price or
        legacy != integer(original.get("quantity_mismatch_rows"), "quantity_mismatch_rows")
        or legacy - resolved + broken != volume or
        legacy > matched or not report.get("eligible_for_automatic_union") is False):
        raise ValueError("Residual source counts or candidate conservation are inconsistent")

    extra = any_diff - volume
    prefix = validated_rows(original, "by_code_prefix_group",
                            matched, amount, price, volume)
    days = validated_rows(original, "by_day", matched, amount, price, volume)
    candidate_by_day = candidate.get("candidate_volume_mismatch_by_day")
    if not isinstance(candidate_by_day, dict) or {
        str(k): integer(v, "candidate_volume_mismatch_by_day")
        for k, v in candidate_by_day.items()
    } != {k: v["volume"] for k, v in days.items() if v["volume"]}:
        raise ValueError("Candidate by-day mismatch distribution is not conserved")

    prefix_bounds = bounds_for_group(prefix, extra)
    day_bounds = bounds_for_group(days, extra)
    exact_masks = exact_masks_if_present(
        candidate, prefix, days, matched, volume, amount, price, any_diff)
    result = {
        "separate_day_section_consistency_checked": verified_day_companion,
        "exact_mask_evidence_present": exact_masks is not None,
        "format": "AStockDataTools offline x100 five-minute residual triage v1",
        "source_result_key": label,
        "period": "5min",
        "from_date": original["from_date"],
        "to_date": original["to_date"],
        "matched_overlap_keys": matched,
        "legacy_volume_mismatch": legacy,
        "candidate_volume_mismatch": volume,
        "amount_mismatch": amount,
        "price_mismatch": price,
        "candidate_any_field_mismatch": any_diff,
        "candidate_no_field_mismatch": matched - any_diff,
        "candidate_any_field_mismatch_pct_of_matched": (
            round(100 * any_diff / matched, 5) if matched else None),
        "nonvolume_only_with_price_or_amount_exact": extra,
        "pairwise_overlap_lower_bounds": {
            "volume_and_amount": intersect_min(volume, amount, any_diff),
            "volume_and_price": intersect_min(volume, price, any_diff),
            "amount_and_price": intersect_min(amount, price, any_diff)
        },
        "three_field_overlap_lower_bound": max(
            0, volume + amount + price - 2 * any_diff),
        "volume_only_lower_bound": max(0, any_diff - amount - price),
        "volume_only_upper_bound": min(volume, any_diff - max(amount, price)),
        "by_code_prefix_group_bounds": prefix_bounds,
        "by_day_bounds": day_bounds,
        "groups_ranked_by_candidate_volume_residual": sorted(
            prefix_bounds, key=lambda g: (-prefix_bounds[g]["candidate_volume_mismatch"], g)),
        "days_ranked_by_candidate_volume_residual": sorted(
            day_bounds, key=lambda d: (-day_bounds[d]["candidate_volume_mismatch"], d)),
        "all_field_overlap_bounds_not_exact_intersections": True,
        "no_field_level_raw_keys_available_from_this_report": True,
        "data_vendor_units_certified": False,
        "safe_to_automatically_union": False,
        "underlying_ohlcv_read": False,
        "underlying_ohlcv_modified": False,
        "original_report_modified": False,
        "source_report_scan_complete": True
    }
    if exact_masks is not None:
        result["verified_exact_disjoint_field_masks"] = exact_masks
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, required=True,
                    help="Existing candidate report JSON; no raw H5 or Parquet is accessed")
    ap.add_argument("--out", type=Path, required=True,
                    help="New JSON file under H5ParquetReconciler/reports/")
    args = ap.parse_args(argv)
    try:
        out, scratch = core.resolve_module_artifact_paths(args.out)
        if out.suffix.lower() != ".json" or not out.is_relative_to(
                (HERE.parent / "reports").resolve()):
            raise ValueError("New report must be JSON under module reports/")
        report_path = args.report.resolve()
        if out == report_path or out.exists():
            raise ValueError("Refusing to overwrite input or an existing output")
        # Only read a report; never scan any source root or index.
        if report_path.suffix.lower() != ".json":
            raise ValueError("Input must be JSON")
        data = json.loads(report_path.read_text(encoding="utf-8"))
        result = analyze(data)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print("Saved offline residual bounds report:", out)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
