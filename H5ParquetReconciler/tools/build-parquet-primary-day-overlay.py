#!/usr/bin/env python3
"""Versioned PRIVATE day-only Parquet overlay from verified H5-gap staging.

Purchased Parquet/H5 remain read-only. Prepared versions are immutable;
activation changes ONLY the module-private active pointer, never a production
query, market file, source conversion, or existing historical Parquet.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent.resolve()
WORK = (MODULE / "work" / "unified_parquet").resolve()
STAGING = WORK / "staging"
VERSIONS = WORK / "versions"
ACTIVE = WORK / "active-day-overlay.json"
VERSION_FORMAT = "AStockDataTools private immutable Parquet day overlay v1"
POINTER_FORMAT = "AStockDataTools private active day overlay pointer v1"


def import_tool(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stage_tool = import_tool("private_day_overlay_stager", "stage-h5-only-day-to-parquet.py")
gate_tool = stage_tool.gate_tool


def digest_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def valid_sha(value):
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Invalid version or file SHA256")
    return value


def safe_private():
    if (not WORK.is_relative_to(MODULE / "work")
            or (MODULE / "work").is_symlink()
            or WORK.is_symlink() or STAGING.is_symlink()
            or VERSIONS.is_symlink() or ACTIVE.is_symlink()):
        raise ValueError("Private overlay paths must not be symlinks or external")


def safe_stage_path(path):
    p = Path(path)
    if not p.is_absolute():
        parts = p.parts
        if parts and parts[0].lower() == MODULE.name.lower():
            parts = parts[1:]
        p = MODULE.joinpath(*parts)
    if p.is_symlink():
        raise ValueError("Symlinked stage directory is prohibited")
    resolved = p.resolve()
    if (resolved.parent != STAGING.resolve() or not resolved.is_dir()
            or (resolved / "manifest.json").is_symlink()
            or (resolved / "day.parquet").is_symlink()):
        raise ValueError("Stage must be a direct existing private staging directory")
    return resolved


def verify_reports(gate_path, source_path):
    gate_path, source_path = Path(gate_path).resolve(), Path(source_path).resolve()
    if (gate_path.parent != (MODULE / "reports").resolve()
            or source_path.parent != (MODULE / "reports").resolve()
            or not gate_path.is_file() or not source_path.is_file()
            or gate_path == source_path):
        raise ValueError("Original and gate reports must exist inside module reports")
    raw = source_path.read_bytes()
    source = json.loads(raw)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    analyzed = gate_tool.analyze(source)
    source_hash = digest_bytes(raw)
    if (gate.get("format") != gate_tool.OUTPUT_FORMAT
            or gate.get("source_report_basename") != source_path.name
            or gate.get("source_report_sha256") != source_hash
            or gate.get("daily_coverage") != analyzed["daily_coverage"]
            or gate.get("source_totals") != analyzed["source_totals"]
            or gate.get("existing_tolerance_ohlc_overlap_pass") is not True
            or gate.get("ready_for_unattended_data_fill") is not False
            or gate.get("safe_to_automatically_union") is not False):
        raise ValueError("Invalid or stale Parquet-primary daily gate")
    # The audit/gate uses compact YYYYMMDD date keys while the staged
    # manifest is deliberately canonical ISO YYYY-MM-DD. Normalize at the
    # trusted boundary instead of comparing two incompatible date formats.
    expected = {
        date.fromisoformat(d["date"]).isoformat(): d["h5_rows"]
        for d in analyzed["daily_coverage"]
        if d["category"] == "entire_date_h5_only_candidate"
    }
    if not expected:
        raise ValueError("Audit has no H5-only complete-date candidates")
    return {"expected": expected, "source_sha": source_hash,
            "gate_sha": stage_tool.file_digest(gate_path),
            "source_basename": source_path.name,
            "gate_basename": gate_path.name}


def inspect_stage(directory, expected, digests):
    import pyarrow.parquet as pq

    root = safe_stage_path(directory)
    meta_path, data_path = root / "manifest.json", root / "day.parquet"
    if not meta_path.is_file() or not data_path.is_file():
        raise ValueError("Missing private stage manifest or Parquet file")
    manifest = json.loads(meta_path.read_text(encoding="utf-8"))
    day_text = manifest.get("day")
    if (day_text not in expected or manifest.get("format") != stage_tool.FORMAT
            or manifest.get("period") != "day"
            or manifest.get("state") != "staged_verified_not_promoted"
            or manifest.get("audited_h5_only_bars") != expected[day_text]
            or manifest.get("staged_bars") != expected[day_text]
            or manifest.get("raw_day_report_sha256") != digests["source_sha"]
            or manifest.get("gate_report_sha256") != digests["gate_sha"]
            or manifest.get("original_market_data_modified") is not False
            or manifest.get("purchased_parquet_overwritten") is not False
            or manifest.get("h5_mirror_created") is not False
            or manifest.get("ready_for_production_promotion") is not False
            or manifest.get("safe_to_automatically_union") is not False
            or manifest.get("h5_daily_price_factor_candidate") != 0.001
            or manifest.get("h5_daily_volume_factor_candidate") != 100
            or manifest.get("h5_daily_amount_factor_candidate") != 1000):
        raise ValueError("Stage is not eligible or not tied to the exact gate")
    date_value = date.fromisoformat(day_text)
    if day_text != date_value.isoformat():
        raise ValueError("Noncanonical staged date")
    initial_hash = stage_tool.file_digest(data_path)
    if initial_hash != valid_sha(manifest.get("staged_parquet_sha256")):
        raise ValueError("Staged file bytes changed since original verification")
    pf = pq.ParquetFile(str(data_path))
    if tuple(pf.schema_arrow.names) != stage_tool.SCHEMA_FIELDS:
        raise ValueError("Staged Parquet column schema differs from expected source format")
    if pf.metadata.num_rows != expected[day_text]:
        raise ValueError("Parquet footer count differs from audit")
    table = pf.read(columns=["ts", "symbol", "source"])
    if table.num_rows != expected[day_text]:
        raise ValueError("Parquet decoded key count differs from audit")
    stamp = int(datetime(date_value.year, date_value.month, date_value.day,
                         tzinfo=stage_tool.core.UTC8).timestamp() * 1000)
    markets, symbols = Counter(), set()
    for item in table.to_pylist():
        sym = stage_tool.core.symbol_id(item["symbol"])
        if (item["ts"] != stamp or item["source"] != "hikyuu_h5_tail_candidate"
                or sym is None
                or not stage_tool.core.is_a_share_candidate(sym, date_value.year)
                or sym in symbols):
            raise ValueError("Wrong date/stock/duplicate/source in staged Parquet")
        symbols.add(sym)
        markets[sym[:2]] += 1
    if markets != Counter(manifest.get("market_prefix_counts", {})):
        raise ValueError("Staged market count disagrees with private manifest")
    if stage_tool.file_digest(data_path) != initial_hash:
        raise ValueError("Staged source file changed while reading")
    return {"day": day_text, "rows": expected[day_text],
            "parquet_sha256": initial_hash,
            "manifest_sha256": stage_tool.file_digest(meta_path),
            "stage_dir": str(root.relative_to(MODULE)).replace("\\", "/"),
            "market_prefix_counts": dict(sorted(markets.items()))}


def validate_stages(paths, evidence):
    if not isinstance(paths, (tuple, list)) or not paths:
        raise ValueError("Supply all audited H5-only date stages")
    prepared = [inspect_stage(p, evidence["expected"], evidence) for p in paths]
    by_date = {item["day"]: item for item in prepared}
    if len(by_date) != len(prepared) or set(by_date) != set(evidence["expected"]):
        raise ValueError("Stage dates must exactly cover the expected complete H5-only days")
    return [by_date[k] for k in sorted(by_date)]


def recheck_live(root, evidence):
    root = Path(root).resolve()
    before = stage_tool.source_file_states(root, date.fromisoformat(
        next(iter(evidence["expected"]))).year)
    scratch = MODULE / "work" / "day_overlay_fresh_check"
    scratch.mkdir(parents=True, exist_ok=True)
    for stamp, expected in sorted(evidence["expected"].items()):
        d = date.fromisoformat(stamp)
        stage_tool.verify_live_absence(root, scratch, d, expected)
    if before != stage_tool.source_file_states(root, date.fromisoformat(
            next(iter(evidence["expected"]))).year):
        raise ValueError("Source files changed during final overlay live audit")


def read_active():
    if not ACTIVE.exists():
        return None
    if ACTIVE.is_symlink():
        raise ValueError("Unsafe active pointer")
    p = json.loads(ACTIVE.read_text(encoding="utf-8"))
    if (not isinstance(p, dict) or set(p) != {"format", "version_sha256"}
            or p["format"] != POINTER_FORMAT):
        raise ValueError("Invalid private active pointer")
    return valid_sha(p["version_sha256"])


def load_version(version_hash):
    valid_sha(version_hash)
    target = VERSIONS / (version_hash + ".json")
    if not target.is_file() or target.is_symlink():
        raise ValueError("Missing private immutable version")
    entry = json.loads(target.read_text(encoding="utf-8"))
    if (not isinstance(entry, dict)
            or entry.get("version_sha256") != version_hash
            or entry.get("format") != VERSION_FORMAT):
        raise ValueError("Invalid private version envelope")
    body = {k: v for k, v in entry.items() if k != "version_sha256"}
    if digest_bytes(canonical(body)) != version_hash:
        raise ValueError("Tampered private version contents")
    previous = entry.get("previous_version_sha256")
    if previous is not None:
        valid_sha(previous)
    return entry


@contextmanager
def locked():
    safe_private()
    WORK.mkdir(parents=True, exist_ok=True)
    lock = WORK / ".day-overlay.lock"
    try:
        fd = os.open(str(lock), os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("Private overlay lock exists; refusing concurrent update") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic_active(sha):
    temp = WORK / ".day-overlay-active.tmp"
    if temp.exists() or temp.is_symlink() or ACTIVE.is_symlink():
        raise ValueError("Stale active pointer temporary file or unsafe link")
    try:
        if sha is None:
            ACTIVE.unlink(missing_ok=True)
            return
        with temp.open("x", encoding="utf-8") as out:
            json.dump({"format": POINTER_FORMAT, "version_sha256": sha}, out,
                      ensure_ascii=False, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, ACTIVE)
    finally:
        temp.unlink(missing_ok=True)


def prepare(root, gate, source, stage_dirs):
    safe_private()
    evidence = verify_reports(gate, source)
    selected = validate_stages(stage_dirs, evidence)
    recheck_live(root, evidence)
    body = {
        "format": VERSION_FORMAT, "period": "day",
        "source_report_basename": evidence["source_basename"],
        "gate_report_basename": evidence["gate_basename"],
        "source_report_sha256": evidence["source_sha"],
        "gate_report_sha256": evidence["gate_sha"],
        "previous_version_sha256": None,
        "stages": selected,
        "rows_in_overlay": sum(row["rows"] for row in selected),
        "status": "prepared_private_day_overlay_not_production",
        "source_parquet_priority": True,
        "purchased_historical_parquet_modified": False,
        "h5_market_files_modified": False,
        "production_query_route_modified": False,
        "safe_to_automatically_union": False,
    }
    with locked():
        previous = read_active()
        if previous is not None:
            load_version(previous)
        body["previous_version_sha256"] = previous
        h = digest_bytes(canonical(body))
        item = {**body, "version_sha256": h}
        VERSIONS.mkdir(parents=True, exist_ok=True)
        target = VERSIONS / (h + ".json")
        if target.exists():
            if load_version(h) != item:
                raise ValueError("Existing version differs")
        else:
            with target.open("x", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
    return {"version_sha256": h, "status": item["status"],
            "prepared_days": [s["day"] for s in selected],
            "private_rows": item["rows_in_overlay"],
            "production_query_route_modified": False}


def activate(root, gate, source, version_hash):
    safe_private()
    with locked():
        record = load_version(version_hash)
        if record["previous_version_sha256"] != read_active():
            raise ValueError("Private active pointer advanced since version was prepared")
        evidence = verify_reports(gate, source)
        if (evidence["source_sha"] != record["source_report_sha256"]
                or evidence["gate_sha"] != record["gate_report_sha256"]):
            raise ValueError("Activation report hashes differ from prepared immutable version")
        current = validate_stages(
            [MODULE / item["stage_dir"] for item in record["stages"]], evidence)
        if current != record["stages"]:
            raise ValueError("Private staged Parquet changed since prepare")
        recheck_live(root, evidence)
        atomic_active(version_hash)
    return {"status": "private_overlay_pointer_activated",
            "version_sha256": version_hash,
            "private_rows": record["rows_in_overlay"],
            "production_query_route_modified": False}


def rollback():
    with locked():
        old = read_active()
        if old is None:
            raise ValueError("No private overlay pointer to rollback")
        entry = load_version(old)
        previous = entry["previous_version_sha256"]
        if previous is not None:
            load_version(previous)
        atomic_active(previous)
    return {"status": "private_pointer_restored_or_disabled",
            "previous_active_sha256": old, "restored_sha256": previous,
            "immutable_versions_preserved": True,
            "production_query_route_modified": False}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--action", choices=("prepare", "activate", "rollback"), required=True)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--gate-report", type=Path)
    ap.add_argument("--source-report", type=Path)
    ap.add_argument("--stage-dirs", type=Path, nargs="+")
    ap.add_argument("--version")
    ap.add_argument("--confirm-private-pointer", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.action in ("prepare", "activate"):
            if not all((args.root, args.gate_report, args.source_report)):
                raise ValueError("Root and both SHA-linked reports required")
            if args.action == "prepare":
                if args.version is not None or not args.stage_dirs:
                    raise ValueError("Prepare needs all --stage-dirs and no --version")
                summary = prepare(args.root, args.gate_report,
                                  args.source_report, args.stage_dirs)
            else:
                if not args.confirm_private_pointer or args.stage_dirs or not args.version:
                    raise ValueError("Explicit --confirm-private-pointer and --version required")
                summary = activate(args.root, args.gate_report,
                                   args.source_report, args.version)
        else:
            if (not args.confirm_private_pointer or args.root or args.gate_report
                    or args.source_report or args.stage_dirs or args.version):
                raise ValueError("Rollback requires only --confirm-private-pointer")
            summary = rollback()
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        print("NO purchased Parquet/H5 writes; NO production query routing changes.")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
