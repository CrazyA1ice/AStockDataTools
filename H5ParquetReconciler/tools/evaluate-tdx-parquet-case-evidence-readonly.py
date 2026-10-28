#!/usr/bin/env python3
"""Fail-closed, SAFE per-stock-day evidence gate over three existing read-only reports.

Only source-pinned *diagnostic* evidence is evaluated; no market files are
opened or transformed, no candidate is materialized, and no production union
is ever authorized. Field-specific conflicts cannot be hidden by 5m agreement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
REPORTS = MODULE / "reports"
FORMAT = "AStockDataTools SAFE TDX Parquet minute daily evidence disposition v1"
PREVIEW_FORMAT = "AStockDataTools read-only TDX-aligned Parquet 241-to-240 minute candidate preview v1"
MECHANISM_FORMAT = "AStockDataTools read-only cross-vendor isolated minute High mechanism v1"
CROSSCYCLE_FORMAT = "AStockDataTools bounded TDX vs Parquet daily and 5min parity audit v1"
RULE_ID = "experimental_tdx_end240_from_pq241_opening_fold_v1"
FIELDS = ("open", "high", "low", "close", "volume", "amount")
FULL_GROUP = "candidate_vs_native_full_240"
MAX_BYTES = 256 * 1024
SHA = re.compile(r"[a-f0-9]{64}\Z")
STOCK = re.compile(r"(?:SH|SZ)[0-9]{6}\Z")


def _in_reports(path, output=False):
    p = Path(path)
    target = p if p.is_absolute() else MODULE / p
    resolved = target.resolve()
    root = REPORTS.resolve()
    if (REPORTS.is_symlink() or target.is_symlink() or
            not resolved.is_relative_to(root) or resolved.suffix != ".json" or
            (output and resolved.exists()) or
            (not output and not resolved.is_file())):
        raise ValueError("Use SAFE input files and NEW output JSON under module reports/")
    return resolved


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys in input evidence")
        result[key] = value
    return result


def _load(file, expected_format):
    path = _in_reports(file)
    before = path.stat()
    if not 0 < before.st_size <= MAX_BYTES:
        raise ValueError("Input SAFE evidence exceeds bounded size or is empty")
    with path.open("rb") as fd:
        raw = fd.read(MAX_BYTES + 1)
    after = path.stat()
    if (len(raw) != before.st_size or before.st_size != after.st_size or
            before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError("Evidence file changed while reading")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ValueError("Nonfinite JSON value")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed SAFE evidence JSON") from exc
    if type(data) is not dict or data.get("format") != expected_format:
        raise ValueError("Unexpected SAFE evidence format")
    return data, hashlib.sha256(raw).hexdigest()


def _sha(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError("Invalid or missing provenance SHA")
    return value


def _boolean(doc, key, expected):
    if type(doc.get(key)) is not bool or doc[key] is not expected:
        raise ValueError("Unsafe/contradictory evidence contract: " + key)


def _metrics(doc, n):
    if type(doc) is not dict or set(doc) != set(FIELDS):
        raise ValueError("Missing or extra six-field evidence metrics")
    matched = {}
    for field in FIELDS:
        m = doc[field]
        if type(m) is not dict:
            raise ValueError("Malformed evidence metric")
        count = m.get("within_diagnostic_tolerance")
        rel = m.get("max_relative_error")
        if (type(m.get("n")) is not int or m["n"] != n or
                type(count) is not int or not 0 <= count <= n or
                type(rel) not in (int, float) or not math.isfinite(rel) or rel < 0):
            raise ValueError("Invalid six-field evidence cardinality or error")
        matched[field] = count
    return matched


def _stat_provenance(preview, mechanism, crosscycle):
    pq_min = preview.get("purchased_source_stat_only_provenance")
    pq_mechanism = mechanism.get("purchased_source_stat_only_provenance")
    pq_cross = crosscycle.get("parquet_stat_only_provenance")
    if (type(pq_min) is not dict or type(pq_mechanism) is not dict or
            type(pq_cross) is not dict or set(pq_min) != {"1min", "5min"} or
            set(pq_mechanism) != {"1min", "5min"} or
            set(pq_cross) != {"5min", "day"}):
        raise ValueError("Missing purchased 1m/5m/day source manifests")
    fingerprints = {}
    for period in ("1min", "5min", "day"):
        refs = [x[period] for x in (pq_min, pq_mechanism, pq_cross)
                if period in x]
        items = []
        for r in refs:
            if (type(r) is not dict or
                    r.get("source_manifest_is_stat_only_not_content_authenticated") is not True or
                    type(r.get("matching_bar_count")) is not int or
                    r["matching_bar_count"] != {"1min": 241, "5min": 48, "day": 1}[period]):
                raise ValueError("Invalid source manifest scope/count")
            items.append(_sha(r.get("source_manifest_stat_only_sha256")))
        if len(set(items)) != 1:
            raise ValueError("Purchased Parquet stat manifest conflicts between reports")
        fingerprints[period] = items[0]
    return fingerprints


def evaluate(preview_file, mechanism_file, crosscycle_file):
    p, digest_p = _load(preview_file, PREVIEW_FORMAT)
    m, digest_m = _load(mechanism_file, MECHANISM_FORMAT)
    c, digest_c = _load(crosscycle_file, CROSSCYCLE_FORMAT)
    symbol = p.get("symbol")
    day = p.get("date")
    if type(symbol) is not str or not STOCK.fullmatch(symbol):
        raise ValueError("Noncanonical symbol")
    if type(day) is not str or date.fromisoformat(day).isoformat() != day:
        raise ValueError("Noncanonical date")
    if any(x.get("symbol") != symbol or x.get("date") != day for x in (m, c)):
        raise ValueError("Evidence bundles do not belong to identical stock-day")
    if m.get("candidate_rule_id") != RULE_ID:
        raise ValueError("Unknown/unversioned candidate rule")
    _boolean(m, "candidate_rule_is_experimental", True)
    for doc, flags in (
        (p, [("eligible_for_automatic_production_union", False),
             ("candidate_ohlcva_exported", False),
             ("original_sources_modified", False),
             ("no_raw_ohlcva_or_individual_times_in_report", True)]),
        (m, [("eligible_for_automatic_production_union", False),
             ("candidate_ohlcva_exported", False),
             ("candidate_materialized", False),
             ("sources_modified", False),
             ("market_ohlcva_or_private_paths_exported", False),
             ("individual_mismatch_minute_or_interval_positions_exported", False)]),
        (c, [("eligible_for_automatic_production_union", False),
             ("source_market_files_modified", False),
             ("staging_or_production_union_performed", False),
             ("tdx_internal_three_period_checked_against_real_bytes", True),
             ("no_raw_ohlcva_or_individual_times_in_report", True)]),
    ):
        for flag, expected in flags:
            _boolean(doc, flag, expected)

    native1 = _sha(p.get("native_source_content_sha256"))
    m_native = m.get("tdx_source_content_sha256")
    c_native = c.get("tdx_source_sha256")
    if type(m_native) is not dict or type(c_native) is not dict:
        raise ValueError("Native TDX source hash maps are missing")
    if (native1 != _sha(m_native.get("1min")) or
            native1 != _sha(c_native.get("1min")) or
            _sha(m_native.get("5min")) != _sha(c_native.get("5min"))):
        raise ValueError("Native TDX content SHA differs between SAFE reports")
    _sha(c_native.get("day"))
    fingerprints = _stat_provenance(p, m, c)

    full = _metrics(p.get(FULL_GROUP), 240)
    minute_mismatch = {field: 240 - count for field, count in full.items()}
    if (type(m.get("minute_comparisons")) is not int or m["minute_comparisons"] != 240 or
            type(m.get("mismatch_counts_by_field")) is not dict or
            m["mismatch_counts_by_field"] != minute_mismatch):
        raise ValueError("Minute field counts conflict between SAFE reports")
    high_count = minute_mismatch["high"]
    if (type(m.get("high_mismatch_records")) is not int or
            m["high_mismatch_records"] != high_count):
        raise ValueError("High mismatch count contradicts summary")
    isolated = high_count == 1 and all(
        minute_mismatch[f] == 0 for f in FIELDS if f != "high")
    _boolean(m, "isolated_high_only", isolated)
    first_metric = _metrics(p.get("candidate_vs_native_first_minute"), 1)
    remaining_metric = _metrics(p.get("candidate_vs_native_remaining_239"), 239)
    preview_five_metric = _metrics(p.get("candidate_240_to_purchased_48_five_minute"), 48)
    for field in FIELDS:
        if full[field] != first_metric[field] + remaining_metric[field]:
            raise ValueError("First+remaining vs full minute comparison cardinalities conflict")
    first_failed = any(v == 0 for v in first_metric.values())
    _boolean(m, "first_minute_any_field_disagreement", first_failed)
    gates = p.get("gates")
    if type(gates) is not dict:
        raise ValueError("Missing candidate preview gates")
    expected_gates = {
        "first_candidate_matches_native": all(v == 1 for v in first_metric.values()),
        "remaining_239_match_native": all(v == 239 for v in remaining_metric.values()),
        "candidate_240_matches_native": all(v == 240 for v in full.values()),
        "candidate_5min_matches_purchased_5min": all(
            v == 48 for v in preview_five_metric.values()),
    }
    for name, value in expected_gates.items():
        _boolean(gates, name, value)
    overall = all(expected_gates.values())
    _boolean(gates, "diagnostic_preview_consistent", overall)
    expected_preview_verdict = (
        "diagnostic_candidate_matches_both_sources_not_production_certified"
        if overall else "diagnostic_candidate_mismatch_do_not_materialize")
    if p.get("preview_verdict") != expected_preview_verdict:
        raise ValueError("Preview verdict contradicts six-field metrics")

    matched_internal = {}
    for key in ("native_1min_aggregated_vs_native_5min",
                "purchased_candidate_1min_aggregated_vs_purchased_5min",
                "native_5min_vs_purchased_5min"):
        counts = _metrics(m.get(key), 48)
        matched_internal[key] = all(n == 48 for n in counts.values())
    for key, group in (
        ("native_1min_internal_5min_all_fields_match", "native_1min_aggregated_vs_native_5min"),
        ("purchased_candidate_1min_internal_5min_all_fields_match", "purchased_candidate_1min_aggregated_vs_purchased_5min"),
        ("cross_source_5min_all_fields_match", "native_5min_vs_purchased_5min")):
        _boolean(m, key, matched_internal[group])
    cross_counts = _metrics(c.get("comparisons", {}).get(
        "tdx_5min_vs_parquet_5min_by_interval"), 48)
    if cross_counts != _metrics(m["native_5min_vs_purchased_5min"], 48):
        raise ValueError("Independent 5-minute cross-vendor metrics disagree")
    daily_groups = c.get("comparisons", {})
    daily_tdx = _metrics(daily_groups.get("tdx_daily_vs_parquet_daily"), 1)
    daily_internal = _metrics(daily_groups.get("parquet_5min_aggregate_vs_parquet_daily"), 1)
    control = all(matched_internal.values())
    high_does_not_set_5min_max = (isolated and not first_failed and control and
        m.get("high_mismatch_source_minute_was_neither_interval_max_count") == 1 and
        m.get("high_mismatch_containing_interval_aggregated_high_disagrees_count") == 0)
    if (isolated and control and
            _metrics(m["native_5min_vs_purchased_5min"], 48)["high"] == 48):
        expected_mechanism_verdict = (
            "isolated_minute_high_disagreement_not_visible_at_5min_tolerance")
    elif not any(minute_mismatch.values()) and control:
        expected_mechanism_verdict = "all_checked_minute_and_five_minute_fields_match"
    else:
        expected_mechanism_verdict = "other_or_cross_period_disagreement_do_not_materialize"
    if m.get("verdict") != expected_mechanism_verdict:
        raise ValueError("High mechanism verdict contradicts six-field metrics")
    if high_does_not_set_5min_max:
        minute_status = "isolated_high_not_five_minute_max_minute_disagreement_remains"
    elif not any(minute_mismatch.values()):
        minute_status = "all_minute_fields_diagnostic_match_not_certified"
    else:
        minute_status = "minute_fields_disagree_do_not_materialize"
    daily_status = {
        "tdx_daily_vs_parquet_daily_volume": (
            "diagnostic_match" if daily_tdx["volume"] == 1 else "mismatch"),
        "parquet_five_minute_sum_vs_parquet_daily_volume": (
            "diagnostic_match" if daily_internal["volume"] == 1 else "mismatch"),
        "all_daily_fields_diagnostic_match": all(
            v == 1 for v in (*daily_tdx.values(), *daily_internal.values())),
    }
    return {
        "format": FORMAT, "symbol": symbol, "date": day,
        "candidate_rule_id": RULE_ID, "candidate_rule_is_experimental": True,
        "source_reports_sha256": {"minute_preview": digest_p,
                                  "isolated_high_mechanism": digest_m,
                                  "day_five_minute_crosscycle": digest_c},
        "tdx_full_source_sha256": {"1min": native1,
                                   "5min": m_native["5min"],
                                   "day": c_native["day"]},
        "purchased_stat_only_fingerprints": fingerprints,
        "minute_field_mismatch_counts": minute_mismatch,
        "minute_disposition": minute_status,
        "cross_source_5min_all_fields_match": matched_internal[
            "native_5min_vs_purchased_5min"],
        "daily_volume_disposition": daily_status,
        "source_evidence_crosschecked": True,
        "purchased_source_content_not_cryptographically_authenticated": True,
        "report_integrity_depends_on_trusted_local_files": True,
        "no_market_source_files_opened": True,
        "no_ohlcva_or_intraday_positions_exported": True,
        "original_sources_modified": False,
        "candidate_materialized": False,
        "production_mapping_certified": False,
        "eligible_for_automatic_production_union": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preview", required=True, type=Path)
    ap.add_argument("--mechanism", required=True, type=Path)
    ap.add_argument("--crosscycle", required=True, type=Path)
    ap.add_argument("--read-only", required=True, action="store_true")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        target = _in_reports(args.out, output=True)
        report = evaluate(args.preview, args.mechanism, args.crosscycle)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as fd:
            json.dump(report, fd, indent=2, ensure_ascii=False, allow_nan=False)
            fd.write("\n")
        print("Saved SAFE minute/daily reconciliation disposition:", target)
        print("Minute:", report["minute_disposition"])
        print("Daily volume:", report["daily_volume_disposition"])
        print("Never authorizes production union; no market files opened.")
    except (ValueError, OSError, TypeError, KeyError, OverflowError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
