"""Explicit read-only V2-D diagnostic CLI.

No subprocess, QMT API, scheduled task, update, financial version writes or
progress state mutation. Does not enable retry or download execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from market_center_v2_faults import FaultEvidenceBlocked, diagnose_latest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", required=True, type=Path)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "V2D_FAULT_DIAGNOSIS_BLOCKED",
            "reason": "explicit_readonly_optin_required",
            "allowed_to_execute": False, "market_file_writes": False,
            "qmt_calls": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    try:
        result = diagnose_latest(args.state_module)
    except (FaultEvidenceBlocked, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "V2D_FAULT_DIAGNOSIS_BLOCKED",
            "reason": str(exc),
            "allowed_to_execute": False, "market_file_writes": False,
            "qmt_calls": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
