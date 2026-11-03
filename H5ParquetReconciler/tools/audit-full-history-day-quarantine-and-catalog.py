#!/usr/bin/env python3
"""Verify already-written 1990-2026 private day catalog; summarize RAW rejects.

No market data is materialized or original H5 / purchased Parquet accessed.
The full21 historical source, 21 annual candidates/quarantines, and accepted
modern 16-year version are SHA rechecked. Individual stock codes and price,
volume, amount values are NEVER exported. Candidate values are NOT certified.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
REPORTS = MODULE / "reports"
YEARS = tuple(range(1990, 2011))
FULL_FORMAT = "1990_2026_day_full_history_private_candidates_with_raw_quarantine_not_activated"
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
YEAR_DIR_RE = re.compile(
    r"work/unified_parquet/pre2011_day_candidates/historical_(19\d\d|200\d|2010)_([0-9a-f]{12})/(purchased_schema_day_candidates|source_native_quarantine)\.parquet\Z"
)

def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

C = load("historical_summary_coordinator", "build-1990-2026-private-day-candidate-version.py")

def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def checked_input(path: Path):
    if (REPORTS.is_symlink() or path.is_symlink() or not path.is_file()
            or path.resolve().parent != REPORTS.resolve()
            or path.stat().st_size > 500000):
        raise ValueError("Expected a bounded regular SHA-pinned module reports file")
    return path

def reason_counts(quarantine: Path):
    """Read ONLY the quarantine_reason column: no licensed OHLCVA is decoded."""
    result = Counter()
    with pq.ParquetFile(quarantine) as reader:
        if "quarantine_reason" not in reader.schema_arrow.names:
            raise ValueError("Quarantine reason column missing")
        for batch in reader.iter_batches(batch_size=8192,
                                         columns=["quarantine_reason"],
                                         use_threads=False):
            for reason in batch.column(0).to_pylist():
                if (type(reason) is not str or not re.fullmatch(
                        r"[a-z][a-z0-9_]{0,110}", reason)):
                    raise ValueError("Unrecognized quarantine reason")
                result[reason] += 1
    return dict(sorted(result.items()))

def audit(candidate_version: Path, expected_sha: str, full21: Path,
          modern: Path, modern_sha: str):
    if any(not SHA_RE.fullmatch(s) for s in (expected_sha, modern_sha)):
        raise ValueError("Require pinned lowercase SHA256s")
    candidate_version = checked_input(candidate_version)
    full21 = checked_input(full21)
    modern = checked_input(modern)
    if sha(candidate_version) != expected_sha:
        raise ValueError("37-year private candidate SAFE SHA changed")
    obj = json.loads(candidate_version.read_text(encoding="utf-8"))
    if (obj.get("status") != FULL_FORMAT
            or obj.get("historical_native_start") != "1990-12-20"
            or obj.get("modern_purchase_first_start") != "2011-01-04"
            or obj.get("raw_1990_2010_h5_rows_preserved") != C.OLD_ROWS
            or obj.get("modern_2011_2026_accepted_private_rows") != C.MODERN_ROWS
            or obj.get("all_1990_2026_source_rows_without_overlap")
                   != C.OLD_ROWS + C.MODERN_ROWS
            or obj.get("historical_candidate_vendor_units_or_corporate_actions_certified") is not False
            or obj.get("historical_candidate_rows_active_in_production_query") is not False
            or obj.get("private_active_pointer_modified") is not False
            or obj.get("original_market_files_or_previous_private_shards_modified") is not False
            or obj.get("modern_all16_version_sha256") != modern_sha
            or set(obj.get("historical_years", {})) != {str(y) for y in YEARS}):
        raise ValueError("37-year candidate manifest has invalid boundaries or unsafe certification")
    original, original_sha = C.W.PROFILE.source_safe(full21)
    if obj["historical_full21_safe_sha256"] != original_sha:
        raise ValueError("Historical RAW source SAFE SHA drift")
    sources = {y: (p, n, digest) for y, p, n, digest
               in C.W.PROFILE.verified_private_files(original)}
    if set(sources) != set(YEARS) or sum(s[1] for s in sources.values()) != C.OLD_ROWS:
        raise ValueError("Historical RAW source ranges/rows are incomplete")
    current = C.Q.version(modern, modern_sha)
    if current["private_total_stockday_records"] != C.MODERN_ROWS:
        raise ValueError("Accepted modern private day total changed")

    year_counts = {}
    all_reasons = Counter()
    total_candidates = 0
    total_quarantine = 0
    for year in YEARS:
        entry = obj["historical_years"][str(year)]
        if not isinstance(entry, dict):
            raise ValueError("Historical annual entry must be an object")
        for kind, suffix in (
            ("candidate", "purchased_schema_day_candidates"),
            ("quarantine", "source_native_quarantine"),
        ):
            rel = entry.get(("candidate" if kind == "candidate" else "quarantine")
                            + "_parquet_relative_path")
            if not isinstance(rel, str):
                raise ValueError("Annual relative path missing")
            match = YEAR_DIR_RE.fullmatch(rel)
            if not match or int(match[1]) != year or match[3] != suffix:
                raise ValueError("Untrusted historical annual candidate/quarantine path")
        child = YEAR_DIR_RE.fullmatch(entry["candidate_parquet_relative_path"])[2]
        if YEAR_DIR_RE.fullmatch(entry["quarantine_parquet_relative_path"])[2] != child:
            raise ValueError("Historical candidate/quarantine folder mismatch")
        report = C.year_report(year, child)
        if (checked_input(report) is None
                or sha(report) != entry.get("year_receipt_sha256")):
            raise ValueError("Historical annual SAFE SHA mismatch")
        verified = C.verified_existing(year, child, original_sha, sources[year])
        n = verified["purchased_schema_candidate_rows_not_vendor_certified"]
        q = verified["lossless_native_quarantine_rows"]
        if (entry.get("candidate_rows_unverified_unit_hypothesis") != n
                or entry.get("native_raw_quarantine_rows") != q
                or entry.get("raw_h5_rows") != n + q
                or n + q != sources[year][1]
                or entry.get("candidate_parquet_sha256") != verified["candidate_parquet_sha256"]
                or entry.get("quarantine_parquet_sha256") != verified["quarantine_parquet_sha256"]):
            raise ValueError("Historical annual SAFE/Parquet row-count or SHA mismatch")
        quarantine_path = MODULE / entry["quarantine_parquet_relative_path"]
        reasons = reason_counts(quarantine_path)
        if (sum(reasons.values()) != q
                or reasons != verified.get("quarantine_by_reason")):
            raise ValueError("Quarantine reason rows disagree with original annual receipt")
        all_reasons.update(reasons)
        total_candidates += n
        total_quarantine += q
        year_counts[str(year)] = {
            "historical_h5_native_rows": n + q,
            "tentative_purchase_schema_candidates": n,
            "native_rows_quarantined": q,
            "quarantine_reasons": reasons,
            "candidate_values_certified": False,
            "candidate_parquet_sha256": entry["candidate_parquet_sha256"],
            "native_quarantine_parquet_sha256": entry["quarantine_parquet_sha256"],
        }
    if (total_candidates + total_quarantine != C.OLD_ROWS
            or total_candidates != obj.get("purchase_schema_historical_hypothesis_rows")
            or total_quarantine != obj.get("historical_native_raw_quarantined_rows")
            or sum(all_reasons.values()) != total_quarantine):
        raise ValueError("All 21 years do not conserve historical RAW stockdays")
    return {
        "format":"AStockDataTools private 1990-2026 day candidate/quarantine SHA-verified research catalog v1",
        "status":"full_history_all21_quarantine_reasons_and_private_day_tiers_sha_reverified_not_activated",
        "historical_window":"1990-12-20..2010-12-31",
        "modern_purchase_first_window":"2011-01-04..2026",
        "historical_native_source_rows":C.OLD_ROWS,
        "historical_purchase_schema_unverified_candidate_rows":total_candidates,
        "historical_native_quarantined_rows":total_quarantine,
        "modern_purchased_first_private_rows":C.MODERN_ROWS,
        "all_history_source_rows_accounted":C.OLD_ROWS + C.MODERN_ROWS,
        "all_historical_quarantine_reasons":dict(sorted(all_reasons.items())),
        "by_year":year_counts,
        "historical_candidate_version_sha256":expected_sha,
        "modern_16_year_version_sha256":modern_sha,
        "historical_raw_full21_source_safe_sha256":original_sha,
        "historical_purchase_schema_semantics_certified":False,
        "historical_candidate_values_active_as_production":False,
        "quarantine_omitted_or_dropped":False,
        "original_market_h5_or_purchased_parquet_opened":False,
        "original_market_or_previous_private_files_modified":False,
        "private_active_pointer_changed":False,
        "ready_for_production_query":False,
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-version-safe", type=Path, required=True)
    p.add_argument("--candidate-version-sha256", required=True)
    p.add_argument("--full21-safe", type=Path, required=True)
    p.add_argument("--modern-version-safe", type=Path, required=True)
    p.add_argument("--modern-version-sha256", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--audit-sha-bound-private-only", action="store_true", required=True)
    args = p.parse_args(argv)
    out = args.out
    if (REPORTS.is_symlink() or out.is_symlink() or out.exists()
            or out.suffix != ".json" or out.resolve().parent != REPORTS.resolve()):
        raise ValueError("Write only a NEW module reports/*.json receipt")
    doc = audit(args.candidate_version_safe, args.candidate_version_sha256,
                args.full21_safe, args.modern_version_safe,
                args.modern_version_sha256)
    with out.open("x", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print("PASS: 1990-2026 all-source day catalog, 21 private shards SHA reverified")
    print("Unverified historical candidates:", doc["historical_purchase_schema_unverified_candidate_rows"])
    print("Losslessly quarantined original RAW:", doc["historical_native_quarantined_rows"])
    print("Original 2011-2026 purchased-first data referenced only:", doc["modern_purchased_first_private_rows"])
    print("Per-year and by-reason aggregate SAFE:", out)
    print("NOT a vendor-certified or active production DAY.")

if __name__ == "__main__":
    main()
