#!/usr/bin/env python3
"""Zero market-data IO: inventory registered private 22,274 daily versions.

Checks existing immutable version envelopes and referenced SAFE byte hashes,
without opening H5/Parquet bars, making any new report, or promoting a source.
This is NOT the full live source/H5/PQ verification required for querying.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "private_22274_day_research_registered_readiness",
    HERE / "register-private-combined-day-22274-version.py")
REG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REG)


def inspect(max_versions=30):
    if type(max_versions) is not int or not 1 <= max_versions <= 100:
        raise ValueError("Invalid registered day version inventory budget")
    REG.safe_private()
    versions = REG.VERSIONS
    if not versions.exists():
        items = []
    else:
        if versions.is_symlink() or not versions.is_dir():
            raise ValueError("Untrusted private daily version directory")
        items = list(versions.iterdir())
        if len(items) > max_versions:
            raise ValueError("Private version directory exceeds safe inspection budget")
    verified = []
    for p in sorted(items):
        if (p.is_symlink() or not p.is_file()
                or not re.fullmatch(r"[a-f0-9]{64}\.json", p.name)):
            raise ValueError("Unrecognized private daily version artifact")
        version = REG.load_version(p.stem)
        if (version["candidate_total_new_stockday_rows"] != 22274
                or version["ready_for_production_query"] is not False
                or version["source_market_files_written"] is not False
                or version["private_or_production_active_pointer_modified"] is not False):
            raise ValueError("Invalid private source readiness/version manifest")
        verified.append(p.stem)
    return {
        "status": ("immutable_private_day_versions_present_live_source_gate_still_required"
                   if verified else "no_registered_22274_private_day_versions"),
        "registered_immutable_versions": verified,
        "registered_immutable_version_count": len(verified),
        "candidate_total_new_stockday_rows_per_version": 22274,
        "candidate_whole_date_rows_per_version": 22191,
        "candidate_mixed_stockday_rows_per_version": 83,
        "ready_for_production": False,
        "ready_for_automatic_market_merge": False,
        "live_h5_purchased_source_reverified_by_this_inventory": False,
        "source_market_bars_opened": False,
        "new_private_version_or_report_written": False,
        "original_market_files_modified": False,
        "active_source_pointer_changed": False,
        "next_gate": (
            "explicit_evidence_config_and_registered_22274_live_verification"
            if verified else "register_private_22274_version_from_existing_verified_stage"
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-versions", type=int, default=30)
    args = p.parse_args(argv)
    print(json.dumps(inspect(args.max_versions), ensure_ascii=False,
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
