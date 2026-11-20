"""Explicitly gated, read-only canonical finance recovery inventory CLI.

No xtquant, no subprocess, no production mutex acquisition, no snapshots
created or copied, no import --apply, no downloads or financial state writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from market_center_v2_recovery_inventory import (
    PreflightBlocked, inspect_recovery_prerequisites,
)
from market_center_v2_faults import FaultEvidenceBlocked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "V2D2B_EXPLICIT_READONLY_OPTIN_REQUIRED",
            "can_execute": False, "qmt_calls": 0,
            "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    try:
        report = inspect_recovery_prerequisites(
            state_module=args.state_module, market_root=args.market_root)
    except (PreflightBlocked, FaultEvidenceBlocked, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "V2D2B_READONLY_INVENTORY_BLOCKED",
            "reason": str(exc)[:180], "can_execute": False,
            "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
