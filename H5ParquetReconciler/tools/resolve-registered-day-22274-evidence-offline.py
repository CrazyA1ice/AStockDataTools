#!/usr/bin/env python3
"""Resolve explicit 22,274-day research evidence from SHA-linked local SAFE.

No H5/Parquet market reads. Resolves exact registered immutable version,
SHA-tied mixed-stage SAFE, live 83-key SAFE, historical ledger, SHA-linked
2016/2026 annual audits, offline 88-key mixed plan, and private key manifest.
Only creates ONE tiny gitignored config if --write-private-config is supplied.
Never guesses a newer file or accepts duplicated/conflicting SHA evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent.resolve()
REPORTS = MODULE / "reports"
WORK = MODULE / "work" / "unified_parquet"
SHA = re.compile(r"[a-f0-9]{64}\Z")
MAX_SAFE_REPORTS = 4000
MAX_REPORT_BYTES = 16000000
CONFIG_FIELDS = ("version_sha256", "live_safe", "private_keys",
                 "history_ledger", "source_2016", "source_2026", "mixed_plan")


def _load(tag, name):
    spec = importlib.util.spec_from_file_location(tag, HERE / name)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


REG = _load("22274_evidence_resolver_immutable_registry",
            "register-private-combined-day-22274-version.py")
PRE = REG.PRE
KEYS = PRE.KEYS
MIXED = PRE.MIXED


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(path, *, max_bytes=MAX_REPORT_BYTES):
    return KEYS.safe_file(path, read=True, max_bytes=max_bytes)


def _json(path):
    return json.loads(Path(path).read_bytes())


def _report_candidates(limit=MAX_SAFE_REPORTS):
    if (REPORTS.is_symlink() or not REPORTS.is_dir()
            or type(limit) is not int or not 1 <= limit <= MAX_SAFE_REPORTS):
        raise ValueError("Unsafe bounded report source directory")
    files = list(REPORTS.iterdir())
    if len(files) > limit:
        raise ValueError("SAFE report listing exceeds bounded metadata budget")
    return files


def _unique_sha_match(files, digest, label):
    if type(digest) is not str or SHA.fullmatch(digest) is None:
        raise ValueError("Malformed expected SAFE SHA for " + label)
    matches = []
    for file in files:
        if (file.suffix.lower() != ".json" or file.is_symlink()
                or not file.is_file()):
            continue
        size = file.stat().st_size
        if not 0 < size <= MAX_REPORT_BYTES:
            continue
        if _hash(file) == digest:
            matches.append(_safe(file))
    if not matches:
        raise ValueError("Missing SHA-linked SAFE report for " + label)
    # Multiple historical receipt filenames with IDENTICAL SHA bytes are
    # equivalent evidence (repeated read-only attestations). Pick the stable
    # basename order; never select by mtime or apparent freshness.
    return sorted(matches, key=lambda x: x.name)[0]


def resolve(version_sha, *, files=None):
    """Resolve *one explicitly supplied* immutable version, no market-value IO."""
    if type(version_sha) is not str or SHA.fullmatch(version_sha) is None:
        raise ValueError("Require explicit SHA256 registered 22,274-day version")
    entry = REG.load_version(version_sha)
    if (entry.get("candidate_total_new_stockday_rows") != PRE.TOTAL_ROWS
            or entry.get("ready_for_production_query") is not False):
        raise ValueError("Not the exact unactivated registered candidate version")
    stage = _safe(REPORTS / entry["mixed_stage_safe_basename"], max_bytes=1000000)
    if _hash(stage) != entry["mixed_stage_safe_sha256"]:
        raise ValueError("Immutable mixed-stage SAFE changed")
    stage_doc = _json(stage)
    if (stage_doc.get("format") != MIXED.FORMAT
            or stage_doc.get("verified_mixed_h5_only_stockday_bars") != 83
            or stage_doc.get("quarantined_2026_07_16_stockday_bars_not_included") != 5
            or stage_doc.get("ready_for_automatic_market_merge") is not False):
        raise ValueError("Untrusted mixed day stage reference")
    files = _report_candidates() if files is None else list(files)
    # Both SHA values came from the *registered* stage; never pick latest.
    live = _unique_sha_match(files, stage_doc["source_live_key_safe_sha256"],
                             "live_83_only_key_safe")
    live_doc = _json(live)
    if (live_doc.get("format") != KEYS.FORMAT
            or live_doc.get("live_verified_nonquarantined_h5_only_stockdays") != 83
            or live_doc.get("quarantined_stockdays_excluded_from_exact_live_keyset") != 5
            or live_doc.get("original_market_files_written") is not False):
        raise ValueError("Untrusted live 83-key SAFE")
    ledger = _unique_sha_match(files, live_doc["original_historical_ledger_sha256"],
                               "historical_day_ledger")
    plan = _unique_sha_match(files, stage_doc["offline_mixed_plan_sha256"],
                             "mixed_88_day_offline_plan")
    body = _json(ledger)
    yearly = body.get("yearly_exact_source_coverage")
    if not isinstance(yearly, list):
        raise ValueError("Historical year-ledger missing SHA-linked annual audits")
    by_year = {x.get("year"):x for x in yearly if isinstance(x, dict)}
    if len(by_year) != len(yearly) or any(y not in by_year for y in (2016,2026)):
        raise ValueError("Historical ledger has duplicate or missing year report")
    sources = {}
    for year in (2016, 2026):
        record = by_year[year]
        basename = record.get("audit_source_report_basename")
        digest = record.get("audit_source_report_sha256")
        if (type(basename) is not str or basename != Path(basename).name
                or type(digest) is not str or SHA.fullmatch(digest) is None):
            raise ValueError("Untrusted SHA-linked original annual source basename")
        report = _safe(REPORTS / basename)
        if _hash(report) != digest:
            raise ValueError("Original annual report SHA mismatch")
        sources[year] = report
    # Live SAFE identifies the actual exact-key private manifest location.
    rel = live_doc.get("private_key_manifest_relative_path")
    if (type(rel) is not str or not re.fullmatch(
            r"work/unified_parquet/mixed_day_key_manifests/"
            r"keys_[0-9a-f]{12,32}/keys\.json", rel)):
        raise ValueError("Untrusted private exact-key manifest relative path")
    private = MODULE / rel
    if (private.is_symlink() or any(p.is_symlink() for p in private.parents
                                   if p.is_relative_to(MODULE))
            or not private.is_file()
            or _hash(private) != live_doc["private_key_manifest_sha256"]):
        raise ValueError("Private live 83-key manifest missing, altered or unsafe")
    # Full source-plan verification is OFFLINE: only reads SAFE JSON and
    # recomputes the historical ledger and 88-key quarantine plan.
    originals, years = KEYS.verified_existing_plan(
        ledger, sources[2016], sources[2026], plan)
    MIXED.read_verified_key_manifest(live, private, originals, years)
    # Load-stage SHA is bound to the registered version; confirm it still
    # references this precise live/key pair.
    if (stage_doc["source_live_key_safe_sha256"] != _hash(live)
            or stage_doc["private_key_manifest_sha256"] != _hash(private)):
        raise ValueError("Registered staged H5 key provenance mismatch")
    return {
        "version_sha256": version_sha,
        "live_safe": str(live),
        "private_keys": str(private),
        "history_ledger": str(ledger),
        "source_2016": str(sources[2016]),
        "source_2026": str(sources[2026]),
        "mixed_plan": str(plan),
    }


def config_path(version_sha):
    if type(version_sha) is not str or SHA.fullmatch(version_sha) is None:
        raise ValueError("Malformed version for private config path")
    return WORK / ("registered-day-research-" + version_sha + ".json")


def prepare(version_sha, *, write=False, files=None):
    evidence = resolve(version_sha, files=files)
    dest = config_path(version_sha)
    if write:
        if (not WORK.is_dir() or WORK.is_symlink() or dest.is_symlink()
                or not dest.resolve().parent == WORK.resolve()):
            raise ValueError("Unsafe private evidence output directory")
        data = json.dumps(evidence, ensure_ascii=False, indent=2,
                          sort_keys=True) + "\n"
        if dest.exists():
            if dest.read_text(encoding="utf-8") != data:
                raise ValueError("Existing private evidence config differs; refusing overwrite")
        else:
            with dest.open("x", encoding="utf-8") as fh:
                fh.write(data)
    return {
        "state": ("private_22274_research_evidence_ready_locally"
                  if write else "private_22274_evidence_paths_verified_no_write"),
        "version_sha256": version_sha,
        "identified_evidence_inputs": len(CONFIG_FIELDS),
        "historical_year_reports_SHA_reconciled": True,
        "private_83_stockday_key_manifest_verified": True,
        "whole_plus_mixed_candidate_count": 22274,
        "live_original_h5_and_purchased_parquet_rechecked_now": False,
        "private_config_path": str(dest) if write else None,
        "private_config_created_or_identical": write,
        "original_market_files_read": False,
        "original_market_files_written": False,
        "market_ohlcva_copied": False,
        "production_source_pointer_changed": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version-sha256", required=True)
    p.add_argument("--write-private-config", action="store_true")
    a = p.parse_args(argv)
    print(json.dumps(prepare(a.version_sha256, write=a.write_private_config),
                     ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
