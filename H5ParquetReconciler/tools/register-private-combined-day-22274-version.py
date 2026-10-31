#!/usr/bin/env python3
"""Prepare an immutable SHA-addressed PRIVATE 22,274-day-candidate logical version.

The existing purchased Parquet always remains authoritative. This registers
references to the independently validated 22,191 whole-date and 83 stock-date
H5-only candidates; it does not merge market files, activate any pointer,
create an H5 mirror, or certify H5 value units.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent.resolve()
WORK = MODULE / "work" / "unified_parquet"
VERSIONS = WORK / "combined_day_versions"
LOCK = WORK / ".combined-day-version-create.lock"
FORMAT = "AStockDataTools immutable private 22191 plus 83 daily candidate logical version v1"
REPORT_FORMAT = "AStockDataTools private 22274 combined day version registration SAFE v1"
STATUS = "prepared_private_combined_day_version_not_active"
MAX_JSON = 100000


def load(label, filename):
    spec = importlib.util.spec_from_file_location(label, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRE = load("private_combined_day_registry_live_preflight",
           "verify-private-combined-day-22274-readonly.py")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def valid_sha(value):
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Invalid immutable private version SHA256")
    return value


def name(value):
    if (type(value) is not str or value != Path(value).name
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.json", value)
            or ".." in value):
        raise ValueError("Invalid module SAFE basename")
    return value


def safe_private():
    if (not WORK.resolve().is_relative_to((MODULE / "work").resolve())
            or any(x.is_symlink() for x in (
                MODULE / "work", WORK, VERSIONS, LOCK))):
        raise ValueError("Unsafe or symlinked private version directory")


@contextmanager
def locked():
    safe_private()
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Concurrent private combined version registration locked") from None
    try:
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def read_audit(path):
    """Only aggregate SAFE from the established read-only live union preflight."""
    candidate = PRE.KEYS.safe_file(path, read=True, max_bytes=MAX_JSON)
    raw = candidate.read_bytes()
    report = json.loads(raw)
    false_fields = ("h5_mirror_created", "new_private_combined_version_created",
                    "private_or_production_active_pointer_modified",
                    "purchased_parquet_replaced", "source_market_files_written",
                    "candidate_source_units_certified", "ready_for_automatic_market_merge")
    if (report.get("format") != PRE.FORMAT
            or report.get("state") != "read_only_union_preflight_passed_not_promoted"
            or report.get("candidate_total_new_stockday_rows") != PRE.TOTAL_ROWS
            or report.get("whole_day_candidate_rows") != PRE.WHOLE_ROWS
            or report.get("mixed_stockday_candidate_rows") != PRE.MIXED_ROWS
            or report.get("quarantined_2026_07_16_stockday_bars_not_included") != 5
            or any(report.get(x) is not False for x in false_fields)
            or any(type(report.get(x)) is not str
                   for x in ("whole_day_overlay_version_sha256",
                             "mixed_stage_safe_sha256",
                             "mixed_stage_parquet_sha256",
                             "mixed_stage_manifest_sha256",
                             "original_source_stat_sha256"))
            or any(not re.fullmatch(r"[a-f0-9]{64}", report[x])
                   for x in ("whole_day_overlay_version_sha256",
                             "mixed_stage_safe_sha256",
                             "mixed_stage_parquet_sha256",
                             "mixed_stage_manifest_sha256",
                             "original_source_stat_sha256"))):
        raise ValueError("Untrusted or incomplete 22,274 read-only union SAFE")
    return candidate, raw, report


def manifest_body(previous_path, previous_raw, fresh_path, fresh_raw, proof,
                  mixed_stage_safe):
    return {
        "format": FORMAT,
        "status": STATUS,
        "period": "day",
        "source_priority": "purchased_parquet_first_exact_symbol_day",
        "whole_day_overlay_version_sha256": proof["whole_day_overlay_version_sha256"],
        "whole_day_candidate_rows": PRE.WHOLE_ROWS,
        "mixed_stockday_candidate_rows": PRE.MIXED_ROWS,
        "candidate_total_new_stockday_rows": PRE.TOTAL_ROWS,
        "mixed_stage_safe_basename": name(Path(mixed_stage_safe).name),
        "mixed_stage_safe_sha256": proof["mixed_stage_safe_sha256"],
        "mixed_stage_parquet_sha256": proof["mixed_stage_parquet_sha256"],
        "mixed_stage_manifest_sha256": proof["mixed_stage_manifest_sha256"],
        "original_source_stat_sha256": proof["original_source_stat_sha256"],
        "original_preflight_safe_basename": name(previous_path.name),
        "original_preflight_safe_sha256": digest(previous_raw),
        "fresh_recheck_safe_basename": name(fresh_path.name),
        "fresh_recheck_safe_sha256": digest(fresh_raw),
        "quarantined_2026_07_16_stockday_bars_not_included": 5,
        "source_market_files_written": False,
        "purchased_parquet_replaced": False,
        "private_or_production_active_pointer_modified": False,
        "h5_mirror_created": False,
        "candidate_source_units_certified": False,
        "ready_for_automatic_market_merge": False,
        "ready_for_production_query": False,
    }


def load_version(version_sha):
    """Read an immutable private manifest; verify content-addressed body."""
    valid_sha(version_sha)
    safe_private()
    path = VERSIONS / (version_sha + ".json")
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size < MAX_JSON):
        raise ValueError("Missing or unsafe immutable combined day version")
    entry = json.loads(path.read_bytes())
    if type(entry) is not dict or entry.get("version_sha256") != version_sha:
        raise ValueError("Malformed combined version envelope")
    body = {k: v for k, v in entry.items() if k != "version_sha256"}
    if (digest(canonical(body)) != version_sha or body.get("format") != FORMAT
            or body.get("status") != STATUS
            or body.get("source_priority") != "purchased_parquet_first_exact_symbol_day"
            or body.get("whole_day_candidate_rows") != PRE.WHOLE_ROWS
            or body.get("mixed_stockday_candidate_rows") != PRE.MIXED_ROWS
            or body.get("candidate_total_new_stockday_rows") != PRE.TOTAL_ROWS
            or body.get("quarantined_2026_07_16_stockday_bars_not_included") != 5
            or any(body.get(k) is not False for k in (
                "source_market_files_written", "purchased_parquet_replaced",
                "private_or_production_active_pointer_modified",
                "h5_mirror_created", "candidate_source_units_certified",
                "ready_for_automatic_market_merge", "ready_for_production_query"))):
        raise ValueError("Untrusted content-addressed combined version")
    for k in ("whole_day_overlay_version_sha256", "mixed_stage_safe_sha256",
              "mixed_stage_parquet_sha256", "mixed_stage_manifest_sha256",
              "original_source_stat_sha256", "original_preflight_safe_sha256",
              "fresh_recheck_safe_sha256"):
        valid_sha(body.get(k))
    for k in ("mixed_stage_safe_basename", "original_preflight_safe_basename",
              "fresh_recheck_safe_basename"):
        name(body.get(k))
    # A manifest SHA protects the declaration; its referenced SAFE files
    # must ALSO still match their recorded byte SHAs before any future query.
    for filename, field in (
        ("original_preflight_safe_basename", "original_preflight_safe_sha256"),
        ("fresh_recheck_safe_basename", "fresh_recheck_safe_sha256"),
        ("mixed_stage_safe_basename", "mixed_stage_safe_sha256"),
    ):
        safe = PRE.KEYS.safe_file(PRE.REPORTS / body[filename], read=True,
                                  max_bytes=MAX_JSON)
        if digest(safe.read_bytes()) != body[field]:
            raise ValueError("Referenced SAFE changed after version registration")
    return entry


def prepare(root, whole_sha, mixed_safe, live_safe, private_keys,
            ledger, source2016, source2026, mixed_plan, prior_safe,
            fresh_recheck_out, report_out):
    safe_private()
    original_path, original_raw, original = read_audit(prior_safe)
    if original["whole_day_overlay_version_sha256"] != valid_sha(whole_sha):
        raise ValueError("Prior union proof belongs to another whole-day version")
    mixed_path = PRE.KEYS.safe_file(mixed_safe, read=True, max_bytes=MAX_JSON)
    mixed_raw = mixed_path.read_bytes()
    if digest(mixed_raw) != original["mixed_stage_safe_sha256"]:
        raise ValueError("Mixed stage SAFE differs from trusted prior union proof")
    fresh_path = PRE.new_report(fresh_recheck_out)
    result_path = PRE.new_report(report_out)
    if (fresh_path == result_path or fresh_path == original_path
            or result_path == original_path
            or fresh_path == mixed_path or result_path == mixed_path):
        raise ValueError("Registration SAFE paths must all be distinct")
    # This is a fresh complete live read of purchased Parquet and H5, not
    # merely a replay of the trusted previous aggregate report.
    fresh = PRE.verify(root, whole_sha, mixed_path, live_safe, private_keys,
                       ledger, source2016, source2026, mixed_plan, fresh_path)
    if fresh != original:
        raise ValueError("New live union preflight differs from accepted prior SAFE")
    _, fresh_raw, fresh_doc = read_audit(fresh_path)
    if (fresh_doc != original or original_path.read_bytes() != original_raw
            or mixed_path.read_bytes() != mixed_raw):
        raise ValueError("Source SAFE changed during version registration")
    body = manifest_body(original_path, original_raw, fresh_path, fresh_raw,
                         original, mixed_path)
    version_sha = digest(canonical(body))
    version = {**body, "version_sha256": version_sha}
    with locked():
        if (original_path.read_bytes() != original_raw
                or mixed_path.read_bytes() != mixed_raw
                or fresh_path.read_bytes() != fresh_raw):
            raise ValueError("Trusted SAFE changed at version-registration commit")
        VERSIONS.mkdir(parents=True, exist_ok=True)
        target = VERSIONS / (version_sha + ".json")
        if target.is_symlink():
            raise ValueError("Version filename is a symlink")
        if target.exists():
            existing = load_version(version_sha)
            if existing != version:
                raise ValueError("Immutable version collision")
        else:
            with target.open("x", encoding="utf-8") as f:
                json.dump(version, f, ensure_ascii=False, sort_keys=True, indent=2)
                f.write("\n")
        if load_version(version_sha) != version:
            raise ValueError("Private version did not roundtrip after creation")
    report = {
        "format": REPORT_FORMAT,
        "state": STATUS,
        "version_sha256": version_sha,
        "whole_day_overlay_version_sha256": whole_sha,
        "mixed_stage_parquet_sha256": body["mixed_stage_parquet_sha256"],
        "whole_day_candidate_rows": PRE.WHOLE_ROWS,
        "mixed_stockday_candidate_rows": PRE.MIXED_ROWS,
        "candidate_total_new_stockday_rows": PRE.TOTAL_ROWS,
        "new_private_combined_version_created": True,
        "private_or_production_active_pointer_modified": False,
        "source_market_files_written": False,
        "purchased_parquet_replaced": False,
        "h5_mirror_created": False,
        "candidate_source_units_certified": False,
        "ready_for_production_query": False,
        "ready_for_automatic_market_merge": False,
    }
    with result_path.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return report


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
    p.add_argument("--prior-union-safe", type=Path, required=True)
    p.add_argument("--fresh-recheck-out", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--original-sources-read-only", action="store_true", required=True)
    a = p.parse_args(argv)
    try:
        result = prepare(a.source_root, a.whole_day_version_sha256,
                         a.mixed_stage_safe, a.live_safe, a.private_keys,
                         a.history_ledger, a.source_2016, a.source_2026,
                         a.mixed_plan, a.prior_union_safe, a.fresh_recheck_out, a.out)
        print("Prepared immutable private combined candidate version:", result["version_sha256"])
        print("Total referenced candidate stock-days:", result["candidate_total_new_stockday_rows"])
        print("SAFE:", a.out)
        print("No production writes, no automatic query route and no pointer changes")
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError):
        p.error("Private 22,274 version registration failed closed; no market writes")


if __name__ == "__main__":
    main()
