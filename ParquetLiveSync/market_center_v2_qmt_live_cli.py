"""Optional V2-D2 user-requested QMT connection check; no data operations.

The exact existing qmt_connect_preflight.probe_once() is called only after the
explicit --explicit-connect-only flag. It checks xtdata.get_client only.
Regardless of availability, finance resume / market writes stay disallowed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from market_center_v2_faults import FaultEvidenceBlocked, diagnose_latest
from market_center_v2_qmt_live import observe_qmt_connection, outstanding_resume_gates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--explicit-connect-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    args = parser.parse_args(argv)
    if not args.explicit_connect_only:
        print(json.dumps({
            "status": "QMT_CONNECTION_PROBE_EXPLICIT_OPTIN_REQUIRED",
            "allowed_to_execute": False, "allowed_to_download": False,
            "market_file_writes": False, "qmt_connection_attempts": 0,
        }, ensure_ascii=False))
        return 2
    try:
        latest = diagnose_latest(args.state_module)
        observation = observe_qmt_connection(
            timeout_seconds=args.timeout_seconds)
    except (FaultEvidenceBlocked, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "QMT_CONNECTION_PROBE_BLOCKED",
            "detail": str(exc)[:180],
            "allowed_to_execute": False, "allowed_to_download": False,
            "market_file_writes": False, "qmt_connection_attempts": 0,
        }, ensure_ascii=False))
        return 2
    report = {
        "status": "V2D2_READONLY_CONNECTION_OBSERVATION_NOT_EXECUTABLE",
        "source_run_day": latest["run_day"],
        "source_run_receipt_sha256": latest["receipt_sha256"],
        "finance_progress_sha256": latest["finance_progress_sha256"],
        "observation": observation,
        "recovery_gates": outstanding_resume_gates(
            latest["finance_resume_preview"], qmt_observation=observation),
        "allowed_to_execute": False,
        "allowed_to_download": False,
        "market_file_writes": False,
        "download_calls": 0,
    }
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
