#!/usr/bin/env python3
"""Read-only, zero-market-I/O evidence-chain audit of three finished JSON reports.

Connect a completed single-day exact 5min H5/PQ audit, the focused 5min
session report, and the H5-only one-to-five-minute aggregation report.
It recomputes provenance and marginal conservation without reading H5 or
Parquet files. This is a conditional candidate-data audit, NOT a data-source
certification or permission to union vendor K-lines.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "chain_audit_core", HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
MASKS = core.CANDIDATE_RESIDUAL_MASKS
PRICE_FIELDS = ("open", "high", "low", "close")


def require(test, message):
    if not test:
        raise ValueError("Evidence chain inconsistent: " + message)


def integer(value, label):
    require(type(value) is int and value >= 0, label + " invalid counter")
    return value


def counts(value, *, allow_sparse=False):
    require(isinstance(value, dict), "missing residual mask map")
    require(set(value).issubset(MASKS) if allow_sparse else set(value) == set(MASKS),
            "unknown/incomplete residual masks")
    require(all(k != "none" for k in value) if allow_sparse else True,
            "sparse conflicts must not contain none")
    return {k: integer(v, k) for k, v in value.items()}


def complete_minute_summary(item, symbol, hypothesis):
    require(isinstance(item, dict), symbol + " " + hypothesis + " missing")
    all_day = item.get("whole_day")
    sessions = item.get("sessions")
    require(isinstance(all_day, dict) and isinstance(sessions, dict)
            and set(sessions) == {"morning", "afternoon"},
            symbol + " minute session provenance incomplete")
    for session_name in ("morning", "afternoon"):
        bucket = sessions[session_name]
        require(isinstance(bucket, dict), symbol + " minute bucket missing")
        for field in ("complete_windows", "incomplete_windows"):
            integer(bucket.get(field), symbol + " " + session_name + " " + field)
        require(bucket["complete_windows"] + bucket["incomplete_windows"] == 24,
                symbol + " wrong number of regular-session windows")
    complete = integer(all_day.get("complete_windows"), symbol + " complete")
    incomplete = integer(all_day.get("incomplete_windows"), symbol + " incomplete")
    require(complete + incomplete == 48, symbol + " total windows")
    for field in ("complete_windows", "incomplete_windows"):
        require(sum(s[field] for s in sessions.values()) == all_day[field],
                symbol + " " + field + " session conservation")
    for sample in (all_day, *sessions.values()):
        n = sample["complete_windows"]
        for name in ("all_ohlc_agree", "amount_agree",
                     "volume_both_zero_windows", "nonzero_volume_windows"):
            require(integer(sample.get(name), name) <= n,
                    symbol + " " + name + " exceeds complete windows")
        require(sample["volume_both_zero_windows"] + sample[
            "nonzero_volume_windows"] == n, symbol + " volume denominator")
        p = sample.get("price_field_agree")
        require(isinstance(p, dict) and set(p) == set(PRICE_FIELDS),
                symbol + " OHLC field histogram")
        require(all(integer(v, k) <= n for k, v in p.items()),
                symbol + " OHLC field denominator")
        for key, max_count in (
                ("volume_match_minute_multiplier", n),
                ("volume_match_nonzero_minute_multiplier", sample["nonzero_volume_windows"])):
            factor = sample.get(key)
            require(isinstance(factor, dict) and set(factor) == {"1", "100"},
                    symbol + " " + key + " invalid")
            require(all(integer(v, k) <= max_count for k, v in factor.items()),
                    symbol + " " + key + " exceeds denominator")
        for factor in ("1", "100"):
            require(sample["volume_match_nonzero_minute_multiplier"][factor]
                    <= sample["volume_match_minute_multiplier"][factor],
                    symbol + " impossible nonzero-factor match count")
    for name in ("all_ohlc_agree", "amount_agree",
                 "volume_both_zero_windows", "nonzero_volume_windows"):
        require(sum(s[name] for s in sessions.values()) == all_day[name],
                symbol + " " + name + " session conservation")
    for key in ("volume_match_minute_multiplier",
                "volume_match_nonzero_minute_multiplier", "price_field_agree"):
        for name, total in all_day[key].items():
            require(sum(s[key][name] for s in sessions.values()) == total,
                    symbol + " " + key + "." + name + " session conservation")
    return all_day


def audit_chain(exact, focused, h5_minute):
    """Validate only aggregated source reports; does not read market files."""
    require(isinstance(exact, dict) and
            exact.get("format") ==
            "AStockDataTools H5-Parquet local coverage/difference report v1" and
            exact.get("status") == "complete" and
            exact.get("eligible_for_automatic_union") is False and
            exact.get("sources_modified") is False and
            exact.get("requested_periods") == ["5min"] and
            exact.get("universe_mode") == "a-share-candidate",
            "exact baseline type / safety flags")
    daystr = exact.get("requested_from_date")
    require(isinstance(daystr, str) and
            exact.get("requested_to_date") == daystr,
            "exact baseline must cover one day")
    try:
        day = date.fromisoformat(daystr)
    except (TypeError, ValueError) as e:
        raise ValueError("Evidence chain inconsistent: invalid baseline date") from e
    require(exact.get("requested_years") == [day.year],
            "exact baseline year")
    section = exact.get("results", {}).get(f"5min/{day.year}")
    require(isinstance(section, dict) and section.get("scan_complete") is True
            and section.get("issues") == []
            and section.get("safe_to_automatically_union") is False
            and section.get("source_units_certified") is False,
            "exact baseline section completeness / safety")
    candidate = section.get("quantity_scale_diagnostics", {}).get(
        "h5_volume_times_100_candidate")
    require(isinstance(candidate, dict)
            and candidate.get("factor_certified") is False
            and candidate.get("exact_masks_are_mutually_exclusive") is True,
            "exact masks source or volume factor provenance")
    global_masks = counts(candidate.get("exact_residual_field_mask_counts"))
    matched = integer(section.get("matched_keys"), "matched")
    require(sum(global_masks.values()) == matched
            and sum(n for k, n in global_masks.items() if k != "none")
                == integer(candidate.get(
                    "candidate_value_mismatch_with_original_price_and_amount_rules"),
                    "candidate_any_mismatch"),
            "global exact-mask conservation")
    for field, expected in (
            ("volume", candidate.get("candidate_volume_mismatch")),
            ("amount", section.get("quantity_scale_diagnostics", {}).get(
                "fields", {}).get("amount", {}).get(
                    "different_by_existing_tolerance")),
            ("price", section.get("price_mismatch_rows"))):
        n = integer(expected, field)
        require(sum(v for k, v in global_masks.items() if field in k) == n,
                field + " marginal")
    require(isinstance(focused, dict)
            and focused.get("format") ==
            "AStockDataTools x100 focused 5min residual session forensic v1"
            and focused.get("date") == daystr
            and focused.get("source_files_modified") is False
            and focused.get("no_raw_ohlcv_exported") is True
            and focused.get("unit_mapping_certified") is False
            and focused.get("safe_to_automatically_union") is False
            and focused.get("h5_five_minute_volume_factor_candidate") == 100,
            "focused report type / date / safety flags")
    require(isinstance(h5_minute, dict)
            and h5_minute.get("format") ==
            "AStockDataTools H5 one-minute top3 no-Parquet check v1"
            and h5_minute.get("date") == daystr
            and h5_minute.get("h5_source_values_modified") is False
            and h5_minute.get("original_report_modified") is False
            and h5_minute.get("raw_ohlcv_exported") is False
            and h5_minute.get("parquet_source_read") is False
            and h5_minute.get("safe_to_automatically_union") is False
            and h5_minute.get("minute_unit_certified") is False
            and h5_minute.get("source_timestamp_mapping_certified") is False
            and h5_minute.get("h5_five_minute_volume_times_100_candidate") is True
            and h5_minute.get("one_minute_volume_factor_candidate_values") == [1, 100]
            and h5_minute.get("minute_start_vs_end_label_hypotheses")
            == ["minute_end_label", "minute_start_label"],
            "H5 minute report type / date / flags")
    symbols = focused.get("selected_symbols")
    require(isinstance(symbols, list) and 1 <= len(symbols) <= 8
            and all(isinstance(s, str) and core.symbol_id(s) == s for s in symbols)
            and len(symbols) == len(set(symbols))
            and h5_minute.get("selected_symbols") == symbols
            and set(focused.get("symbol_results", {})) == set(symbols)
            and set(h5_minute.get("symbol_results", {})) == set(symbols),
            "three reports disagree on selected symbol identities")
    top = candidate.get("exact_residual_top_stock_days")
    require(isinstance(top, list) and len(top) >= len(symbols),
            "global exact-mask report lacks top stock-days")
    selected = {}
    for record in top[:len(symbols)]:
        require(isinstance(record, dict)
                and record.get("day") == day.strftime("%Y%m%d")
                and isinstance(record.get("symbol"), str),
                "invalid top stock-day record")
        sym = record["symbol"]
        require(sym not in selected, "duplicate top stock-day symbol")
        mm = counts(record.get("field_mask_counts"), allow_sparse=True)
        require(sum(mm.values()) == integer(
            record.get("candidate_conflicting_bars"), "top conflicting bars"),
            "global top stock-day masks")
        selected[sym] = mm
    require(list(selected) == symbols, "focused choice is not baseline top list")

    rows = []
    total_ohlc = total_amount = total_volume = total_complete = 0
    total_start_complete = total_start_ohlc = 0
    total_conflicts = total_triple = 0
    for symbol in symbols:
        focus = focused["symbol_results"][symbol]
        minute = h5_minute["symbol_results"][symbol]
        require(isinstance(focus, dict)
                and focus.get("status") == "hypothesis_diagnostic_only"
                and focus.get("candidate_volume_factor_h5") == 100
                and focus.get("h5_5min_bars") == 48
                and focus.get("parquet_5min_bars") == 48
                and focus.get("h5_only_bars") == 0
                and focus.get("parquet_only_bars") == 0,
                symbol + " noncomparable focused 5min coverage")
        smasks = counts(focus.get("exact_residual_masks"))
        require(sum(smasks.values()) == 48 and
                {k: v for k, v in smasks.items() if k != "none" and v}
                == selected[symbol], symbol + " focus/exact masks mismatch")
        sessions = focus.get("sessions")
        require(isinstance(sessions, dict)
                and set(sessions) == {"morning", "afternoon"},
                symbol + " five-minute session coverage")
        for name in ("morning", "afternoon"):
            bucket = sessions[name]
            require(bucket.get("matched_bars") == 24
                    and sum(counts(bucket.get("exact_residual_masks")).values()) == 24
                    and bucket.get("volume", {}).get("matched_bars") == 24
                    and bucket.get("amount", {}).get("matched_bars") == 24,
                    symbol + " " + name + " session mask/volume denominator")
        for label in MASKS:
            require(sum(sessions[n]["exact_residual_masks"][label]
                        for n in ("morning", "afternoon")) == smasks[label],
                    symbol + " session masks not conserved")
        reported_volume_net_zero = all(
            bucket.get("volume", {}).get("net_difference_pct_of_h5_total") == 0
            and bucket.get("volume", {}).get(
                "source_total_ratio_parquet_over_h5") == 1.0
            for bucket in (
                focus.get("conservation_on_matched_keys_only", {}),
                *sessions.values())
        )
        require(minute.get("availability") in (
            "candidate_windows_available",
            "not_verifiable_no_one_minute_data",
            "not_verifiable_no_complete_one_minute_windows",
            "not_verifiable_duplicate_one_minute_keys"),
            symbol + " unknown 1min availability")
        one_source = minute.get("one_minute_source")
        require(isinstance(one_source, dict)
                and integer(one_source.get("one_minute_rows"), "1min rows") >= 0,
                symbol + " 1min provenance")
        hypotheses = minute.get("minute_convention_candidates")
        require(isinstance(hypotheses, dict), symbol + " missing minute conventions")
        enough = minute["availability"] == "candidate_windows_available"
        if enough:
            require(set(hypotheses) == {
                "minute_end_label", "minute_start_label"},
                symbol + " missing time hypotheses")
            end = complete_minute_summary(
                hypotheses["minute_end_label"], symbol, "minute_end_label")
            start = complete_minute_summary(
                hypotheses["minute_start_label"], symbol, "minute_start_label")
            require(one_source.get("file_present") is True
                    and one_source.get("dataset_present") is True
                    and one_source.get("duplicate_minute_keys") == 0,
                    symbol + " H5 minute data source status")
            n = end["complete_windows"]
            end_exact = (one_source["one_minute_rows"] == 240
                and n == 48 and end["incomplete_windows"] == 0
                and end["all_ohlc_agree"] == n
                and end["amount_agree"] == n
                and end["nonzero_volume_windows"] == n
                and end["volume_match_nonzero_minute_multiplier"]["100"] == n
                and end["volume_match_nonzero_minute_multiplier"]["1"] == 0)
            label_better = (end_exact and
                start["all_ohlc_agree"] < end["all_ohlc_agree"])
            total_ohlc += end["all_ohlc_agree"]
            total_amount += end["amount_agree"]
            total_volume += end["volume_match_nonzero_minute_multiplier"]["100"]
            total_complete += end["complete_windows"]
            total_start_complete += start["complete_windows"]
            total_start_ohlc += start["all_ohlc_agree"]
        else:
            require(not hypotheses, symbol + " impossible minute unavailable evidence")
            end_exact = label_better = False
        conflicts = 48 - smasks["none"]
        total_conflicts += conflicts
        total_triple += smasks["volume_amount_price"]
        rows.append({
            "symbol": symbol,
            "five_minute_matched_bars": 48,
            "five_minute_candidate_conflicts": conflicts,
            "three_field_conflict_bars": smasks["volume_amount_price"],
            "h5_one_minute_rows": one_source["one_minute_rows"],
            "h5_end_labeled_ohlcv_amount_48_of_48_reaggregates":
                end_exact,
            "end_timestamp_hypothesis_better_than_start_on_ohlc":
                label_better,
            "parquet_vs_h5_5min_volume_net_zero_at_report_precision":
                reported_volume_net_zero,
            "evidence_level": (
                "h5_internal_window_and_x100_candidate_reproduced"
                if end_exact else "insufficient_h5_one_minute_evidence"),
        })
    return {
        "format": "AStockDataTools offline five-minute source-evidence chain v1",
        "date": daystr,
        "symbols": symbols,
        "global_five_minute": {
            "matched_bars": matched,
            "any_candidate_conflict_bars": matched - global_masks["none"],
            "candidate_volume_conflict_bars": candidate["candidate_volume_mismatch"],
            "candidate_price_conflict_bars": section["price_mismatch_rows"],
            "global_exact_residual_masks": global_masks,
        },
        "selected_three_stock_days": {
            "five_minute_bars": 48 * len(symbols),
            "five_minute_candidate_conflicts": total_conflicts,
            "three_field_conflict_bars": total_triple,
            "h5_end_label_complete_windows": total_complete,
            "h5_end_label_ohlc_agreements": total_ohlc,
            "h5_end_label_amount_agreements": total_amount,
            "h5_end_label_nonzero_volume_x100_agreements": total_volume,
            "h5_start_label_complete_windows": total_start_complete,
            "h5_start_label_ohlc_agreements": total_start_ohlc,
            "all_selected_h5_end_label_reaggregations_reproduced": all(
                item["h5_end_labeled_ohlcv_amount_48_of_48_reaggregates"]
                for item in rows),
        },
        "symbol_evidence": rows,
        "interpretation": {
            "observed_end_labeled_1min_h5_aggregation": (
                "Candidate consistent with H5 5min on selected date; "
                "not official timestamp/volume-unit certification"),
            "parquet_5min_boundary_or_allocation_difference": (
                "Supported as hypothesis by rounded zero session net volume, "
                "nonzero per-bar gross differences, and H5 internal agreement; "
                "does not identify which vendor is authoritative"),
            "h5_1min_is_independent_vendor_ground_truth": False,
            "direct_parquet_vs_h5_one_minute_comparison_performed": False,
            "timestamp_mapping_certified": False,
            "volume_unit_certified": False,
            "price_amount_rules_certified": False,
            "security_master_certified": False,
        },
        "source_market_files_read": False,
        "source_market_files_modified": False,
        "input_reports_modified": False,
        "safe_to_automatically_union": False,
        "next_read_strategy": (
            "Avoid new multi-million-row Parquet scans without an indexed "
            "row-group/symbol query plan or data-vendor boundary documentation"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exact-report", type=Path, required=True)
    ap.add_argument("--focused-report", type=Path, required=True)
    ap.add_argument("--h5-minute-report", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        output, _ = core.resolve_module_artifact_paths(args.out, None)
        if (output.suffix.lower() != ".json"
            or not output.is_relative_to((HERE.parent / "reports").resolve())):
            raise ValueError("Output must be a JSON inside module reports/")
        paths = [args.exact_report.resolve(), args.focused_report.resolve(),
                 args.h5_minute_report.resolve()]
        if (len(set(paths)) != len(paths) or output in paths or output.exists()
            or any(p.suffix.lower() != ".json" for p in paths)):
            raise ValueError("Input JSON reports must be distinct; never overwrite")
        reports, fingerprints = [], {}
        for path, label in zip(
                paths, ("exact_masks", "focused_sessions", "h5_one_minute")):
            raw = path.read_bytes()
            reports.append(json.loads(raw.decode("utf-8")))
            fingerprints[label] = {
                "file": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        require(reports[1].get("baseline_report_name") == paths[0].name
                and reports[2].get("baseline_report_name") == paths[1].name,
                "input report filename provenance chain")
        result = audit_chain(*reports)
        result["input_report_provenance"] = fingerprints
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        print("Saved offline provenance chain:", output)
    except (OSError, ValueError, TypeError, KeyError,
            AttributeError, json.JSONDecodeError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
