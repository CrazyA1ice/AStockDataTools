"""Explicit read-only CLI for bounded historical finance backup inventory.

This CLI never copies backups, checks the writer mutex, calls QMT, downloads,
or executes/authorizes a financial sweep. This is metadata ONLY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from market_center_v2_faults import FaultEvidenceBlocked
from market_center_v2_recovery_inventory import PreflightBlocked
from market_center_v2_finance_history_scope import inventory_historical_versions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "V2D2C_EXPLICIT_READONLY_REQUIRED",
            "can_execute": False, "can_download": False,
            "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    try:
        result = inventory_historical_versions(
            state_module=args.state_module, market_root=args.market_root)
    except (FaultEvidenceBlocked, PreflightBlocked, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "V2D2C_READONLY_HISTORY_INVENTORY_BLOCKED",
            "reason": str(exc)[:180], "can_execute": False,
            "can_download": False, "qmt_calls": 0,
            "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
