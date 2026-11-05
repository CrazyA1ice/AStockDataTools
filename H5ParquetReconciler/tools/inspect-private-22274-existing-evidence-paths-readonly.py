#!/usr/bin/env python3
"""Read-only local evidence-path discovery for an existing immutable 22274 day version.

No H5, market Parquet, OHLCVA, price output, report file, or auto-routing.
Print private evidence filenames only. Never automatically choose ambiguous
candidates or assemble a config from unverified filename guesses.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "private_22274_evidence_locator_registry",
    HERE / "register-private-combined-day-22274-version.py")
REG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REG)

VERSION = re.compile(r"[0-9a-f]{64}\Z")
# These substrings only narrow *filename discovery*. None certifies
# that a file belongs to the immutable version or authorizes query use.
PATTERNS = {
    "live_safe": ("live-mixed", "live-safe", "live-h5"),
    "private_keys": ("private-keys", "mixed-day-keys", "live-mixed-day"),
    "history_ledger": ("history-day-ledger",),
    "source_2016": ("historical-day-exact-2016",),
    "source_2026": ("historical-day-exact-2026",),
    "mixed_plan": ("mixed-day", "mixed-stockday"),
}


def inspect(version, *, max_files=2500):
    if not VERSION.fullmatch(version):
        raise ValueError("Require exact registered SHA256 identifier")
    if type(max_files) is not int or not 1 <= max_files <= 10000:
        raise ValueError("Unsafe evidence discovery budget")
    entry = REG.load_version(version)  # verify manifest + referenced SAFE hashes
    reports = MODULE / "reports"
    if reports.is_symlink() or not reports.is_dir():
        raise ValueError("Unsafe/missing trusted local reports directory")
    paths = sorted(reports.iterdir(), key=lambda p: p.name)
    if len(paths) > max_files:
        raise ValueError("Reports directory exceeds read-only discovery budget")
    matched = {}
    for role, fragments in PATTERNS.items():
        names = []
        for p in paths:
            if (p.is_symlink() or not p.is_file()
                    or p.suffix.lower() != ".json"
                    or not p.resolve().is_relative_to(reports.resolve())):
                continue
            if any(fragment in p.name.lower() for fragment in fragments):
                names.append(p.name)
        matched[role] = {
            "file_count": len(names),
            "sample_names": names[-8:],
            "identity_sha_bound_to_registered_version": False,
        }
    return {
        "status": "private_22274_registered_version_trusted_evidence_paths_not_yet_attested",
        "version_sha256": version,
        "candidate_rows": entry["candidate_total_new_stockday_rows"],
        "whole_day_rows": entry["whole_day_candidate_rows"],
        "mixed_stockday_rows": entry["mixed_stockday_candidate_rows"],
        "registered_reference_safes": {
            "mixed_stage_safe_basename": entry["mixed_stage_safe_basename"],
            "original_preflight_safe_basename": entry["original_preflight_safe_basename"],
            "fresh_recheck_safe_basename": entry["fresh_recheck_safe_basename"],
        },
        "evidence_file_discovery": matched,
        "market_data_opened": False,
        "live_h5_purchased_reverified": False,
        "config_written": False,
        "automatic_evidence_selection_permitted": False,
        "production_activated": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version-sha256", required=True)
    p.add_argument("--max-files", type=int, default=2500)
    a = p.parse_args(argv)
    print(json.dumps(inspect(a.version_sha256, max_files=a.max_files),
                     indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
