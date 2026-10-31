#!/usr/bin/env python3
"""Fail-closed, read-only 22,191 whole-day + 83 mixed stock-day union preflight.

No market source writes, private version registration, pointer updates or H5 mirror.
Only emits an aggregate SAFE report after every live source and SHA-bound gate passes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent.resolve()
REPORTS = MODULE / "reports"
FORMAT = "AStockDataTools private full plus mixed H5-only day union preflight v1"
WHOLE_DATES = {"2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"}
WHOLE_ROWS = 22191
MIXED_ROWS = 83
TOTAL_ROWS = 22274


def load(label, filename):
    spec = importlib.util.spec_from_file_location(label, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WHOLE = load("union_day_whole_query", "query-parquet-primary-day-overlay-readonly.py")
MIXED = load("union_day_mixed_stage", "stage-private-mixed-h5-day-83-bars.py")
KEYS = MIXED.KEYS
OVERLAY = WHOLE.versioner


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def new_report(path):
    p = Path(path)
    if (REPORTS.is_symlink() or p.is_symlink() or p.suffix.lower() != ".json"
            or p.resolve().parent != REPORTS.resolve() or p.exists()):
        raise ValueError("Require a NEW direct module reports JSON; no overwrite")
    return p.resolve()


def verify_mixed_stage(stage_safe, live_safe, private_keys, originals, year_dates):
    """All private stock identifiers remain in the local ignored work tree."""
    safe_path = KEYS.safe_file(stage_safe, read=True, max_bytes=1000000)
    doc = json.loads(safe_path.read_bytes())
    required_false = ("candidate_source_units_certified",
                      "h5_mirror_created", "source_market_files_written",
                      "purchased_parquet_replaced",
                      "private_or_production_active_pointer_modified",
                      "ready_for_automatic_market_merge")
    if (doc.get("format") != MIXED.FORMAT or doc.get("action") != "stage"
            or doc.get("state") != "private_stage_prepared_not_promoted"
            or doc.get("stage_parquet_created") is not True
            or doc.get("stage_row_count") != MIXED_ROWS
            or doc.get("verified_mixed_h5_only_stockday_bars") != MIXED_ROWS
            or doc.get("verified_year_counts") != {"2016": 1, "2026": 82}
            or doc.get("quarantined_2026_07_16_stockday_bars_not_included") != 5
            or any(doc.get(k) is not False for k in required_false)
            or doc.get("source_conversion_price_factor_candidate") != 0.001
            or doc.get("source_conversion_daily_volume_factor_candidate") != 100
            or doc.get("source_conversion_amount_factor_candidate") != 1000):
        raise ValueError("Mixed stage SAFE is not a certified isolated candidate")
    _, live_raw, _, private_raw, evidence, selected = MIXED.read_verified_key_manifest(
        live_safe, private_keys, originals, year_dates)
    if (doc.get("source_live_key_safe_sha256") != hashlib.sha256(live_raw).hexdigest()
            or doc.get("private_key_manifest_sha256") != hashlib.sha256(private_raw).hexdigest()
            or doc.get("offline_mixed_plan_sha256") != MIXED.sha256(originals["plan"][1])
            or doc.get("source_stat_sha256") != evidence["original_source_stat_sha256"]):
        raise ValueError("Mixed stage provenance differs from live H5-only key evidence")
    rel = doc.get("private_stage_relative_dir")
    if type(rel) is not str or not re.fullmatch(
            r"work/unified_parquet/mixed_day_stages/mixed_[0-9a-f]{12,32}", rel):
        raise ValueError("Mixed private stage must live in the exact module work tree")
    folder = MODULE / rel
    if (folder.resolve().parent != MIXED.STAGES.resolve()
            or any(p.is_symlink() for p in
                   (MODULE / "work", MIXED.UNIFIED, MIXED.STAGES, folder,
                    folder / "day.parquet", folder / "manifest.json"))
            or not folder.is_dir()):
        raise ValueError("Mixed stage escaped module-private directory")
    data = folder / "day.parquet"
    meta = folder / "manifest.json"
    if not data.is_file() or not meta.is_file():
        raise ValueError("Mixed stage Parquet or manifest missing")
    manifest = json.loads(meta.read_bytes())
    fingerprint = sha(data)
    if (fingerprint != doc.get("private_staged_parquet_sha256")
            or fingerprint != manifest.get("private_stage_sha256")
            or manifest.get("format") != MIXED.STAGE_FORMAT
            or manifest.get("status") != "private_candidate_not_active"
            or manifest.get("staged_bar_count") != MIXED_ROWS
            or manifest.get("candidate_units_certified") is not False
            or manifest.get("not_ready_for_production") is not True
            or manifest.get("active_pointer_changed") is not False
            or manifest.get("source_market_files_written") is not False
            or manifest.get("purchased_parquet_replaced") is not False
            or manifest.get("source_live_key_safe_sha256") != MIXED.sha256(live_raw)
            or manifest.get("private_key_manifest_sha256") != MIXED.sha256(private_raw)
            or manifest.get("source_market_stat_sha256") != doc["source_stat_sha256"]):
        raise ValueError("Mixed private Parquet SHA or provenance changed")
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(data)
    if (tuple(parquet.schema_arrow.names) != MIXED.STAGE.SCHEMA_FIELDS
            or parquet.metadata.num_rows != MIXED_ROWS):
        raise ValueError("Mixed private Parquet schema or footer row count changed")
    actual = parquet.read().to_pylist()
    if len(actual) != MIXED_ROWS:
        raise ValueError("Mixed private Parquet decoded count changed")
    return doc, selected, data, meta, fingerprint, actual, safe_path


def verify(root, whole_sha, mixed_safe, live_safe, private_keys,
           ledger, source2016, source2026, mixed_plan, out,
           timing_sink=None):
    if timing_sink is not None and type(timing_sink) is not dict:
        raise ValueError("Internal phase timing sink must be a dictionary")
    clock = time.perf_counter()
    def lap(label):
        nonlocal clock
        now = time.perf_counter()
        if timing_sink is not None:
            timing_sink[label] = round(now-clock, 6)
        clock = now
    root = Path(root).resolve()
    output = new_report(out)
    if (not (root / "HikyuuData").is_dir()
            or not (root / "AllCycleAStockData" / "day").is_dir()
            or MODULE.is_relative_to(root) or root.is_relative_to(MODULE)):
        raise ValueError("Original market source root invalid or overlaps project")
    whole, evidence, stages = WHOLE.verified_version(whole_sha, 30000)
    if (whole.get("rows_in_overlay") != WHOLE_ROWS
            or len(stages) != 4
            or {item["day"] for item in stages} != WHOLE_DATES
            or sum(x["rows"] for x in stages) != WHOLE_ROWS):
        raise ValueError("Not the audited exact four full-market missing dates")
    lap("whole_immutable_overlay_validation_seconds")
    originals, year_dates = KEYS.verified_existing_plan(
        ledger, source2016, source2026, mixed_plan)
    lap("mixed_offline_plan_and_ledger_verification_seconds")
    before = KEYS.state_digest(root, (2016, 2026))
    lap("original_source_stat_digest_before_seconds")
    doc, selected, stage_data, stage_meta, mixed_hash, actual, safe_path = (
        verify_mixed_stage(mixed_safe, live_safe, private_keys, originals, year_dates))
    original_stage_safe_hash = sha(safe_path)
    original_private_keys_hash = sha(private_keys)
    original_live_safe_hash = sha(live_safe)
    if doc["source_stat_sha256"] != before:
        raise ValueError("Original market files changed since 83-key verification")
    mixed_days = {
        f"{stamp // 100000000:04d}-{stamp // 1000000 % 100:02d}-{stamp // 10000 % 100:02d}"
        for _, stamp in selected
    }
    if mixed_days & WHOLE_DATES or len(selected) != MIXED_ROWS:
        raise ValueError("Mixed candidate overlaps full-market staged dates")
    lap("mixed_stage_manifest_sha_and_parquet_verification_seconds")
    MIXED.verify_all_live_absence(root, year_dates, selected)
    lap("mixed_years_exact_purchased_h5_key_scan_seconds")
    expected = MIXED.normalize_private_h5_rows(root, selected)
    lap("mixed_original_h5_83_value_normalization_seconds")
    if actual != expected:
        raise ValueError("Mixed private Parquet differs from original H5 candidate rows")
    # Purchased Parquet has no keys on audited whole dates, and no purchased
    # stock-day key overlaps selected mixed keys; both rechecked on live originals.
    OVERLAY.recheck_live(root, evidence)
    lap("whole_four_days_original_market_recheck_seconds")
    if (KEYS.state_digest(root, (2016, 2026)) != before
            or sha(stage_data) != mixed_hash
            or sha(safe_path) != original_stage_safe_hash
            or sha(private_keys) != original_private_keys_hash
            or sha(live_safe) != original_live_safe_hash
            or any(p.read_bytes() != raw for p, raw in originals.values())):
        raise ValueError("Trusted inputs changed during complete preflight")
    # Reverify the four existing whole-date stages and version content after
    # the live source reads. No market or private version writes occur here.
    lap("after_market_source_stat_and_provenance_checks_seconds")
    whole2, evidence2, stages2 = WHOLE.verified_version(whole_sha, 30000)
    if whole2 != whole or evidence2 != evidence or stages2 != stages:
        raise ValueError("Immutable whole-day version changed during verification")
    lap("whole_immutable_overlay_second_validation_seconds")
    result = {
        "format": FORMAT,
        "state": "read_only_union_preflight_passed_not_promoted",
        "whole_day_overlay_version_sha256": whole_sha,
        "whole_day_candidate_rows": WHOLE_ROWS,
        "mixed_stage_parquet_sha256": mixed_hash,
        "mixed_stage_manifest_sha256": sha(stage_meta),
        "mixed_stage_safe_sha256": sha(safe_path),
        "mixed_stockday_candidate_rows": MIXED_ROWS,
        "candidate_total_new_stockday_rows": TOTAL_ROWS,
        "quarantined_2026_07_16_stockday_bars_not_included": 5,
        "original_source_stat_sha256": before,
        "source_market_files_written": False,
        "purchased_parquet_replaced": False,
        "private_or_production_active_pointer_modified": False,
        "new_private_combined_version_created": False,
        "h5_mirror_created": False,
        "candidate_source_units_certified": False,
        "ready_for_automatic_market_merge": False,
    }
    with output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    lap("safe_report_file_creation_seconds")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--whole-day-version-sha256", required=True)
    p.add_argument("--mixed-stage-safe", type=Path, required=True)
    p.add_argument("--live-safe", type=Path, required=True)
    p.add_argument("--private-keys", type=Path, required=True)
    p.add_argument("--history-ledger", type=Path, required=True)
    p.add_argument("--source-2016", type=Path, required=True)
    p.add_argument("--source-2026", type=Path, required=True)
    p.add_argument("--mixed-plan", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--original-sources-read-only", action="store_true", required=True)
    a = p.parse_args(argv)
    try:
        r = verify(a.source_root, a.whole_day_version_sha256, a.mixed_stage_safe,
                   a.live_safe, a.private_keys, a.history_ledger,
                   a.source_2016, a.source_2026, a.mixed_plan, a.out)
        print("Verified stock-day candidate rows:", r["candidate_total_new_stockday_rows"])
        print("Read-only union preflight SAFE:", a.out)
        print("No combined version, source writes or pointer changes")
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError):
        p.error("Private 22,274 day union preflight failed closed; no market writes")


if __name__ == "__main__":
    main()
