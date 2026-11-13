#!/usr/bin/env python3
"""Read-only SHA audit of the completed 184-stock QMT day-recovery receipts.

This command never calls xtquant, downloads bars or mutates any source.
It is the safe restart gate for the eltdx full-market minute audit.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

import qmt_1m_pipeline as P
import qmt_1m_recover as R


def verify(root, *, logger=print):
    start, end = R.START, R.END
    stage = P.BASE / f"{start:%Y%m%d}_{end:%Y%m%d}"
    expected, stocks, plan, calib = R.load_bound_context(Path(root), stage, start, end)
    originals = R.validate_original(stage, expected, stocks, progress=logger)
    missing = [code for code in stocks if code not in originals]
    fingerprint = P.sha_bytes(P.canonical({
        "original_plan_sha256": P.sha_bytes(P.canonical(plan)),
        "calibration_sha256": plan["calibration_sha256"],
        "format": R.FORMAT,
    }))
    recovery = stage / "day_recovery"
    recovered = {}
    for code in missing:
        days = sorted(d.isoformat() for d, universe in expected.items()
                      if code in universe)
        doc = R.validate_recovery_receipt(recovery, code, fingerprint, days)
        if doc is not None:
            recovered[code] = doc
    expected_keys = sum(len(v) for v in expected.values())
    full_keys = sum(len(doc["traded_days"]) for doc in originals.values())
    recovered_keys = sum(len(doc["approved_days"]) for doc in recovered.values())
    missing_keys = expected_keys - full_keys - recovered_keys
    result = {
        "format": "qmt_original_plus_day_recovery_sha_preflight_v1",
        "stocks": len(stocks),
        "original_full_stock_receipts_verified": len(originals),
        "expected_recovery_receipts": len(missing),
        "recovery_receipts_sha_verified": len(recovered),
        "missing_recovery_receipts": len(missing) - len(recovered),
        "expected_stock_day_keys": expected_keys,
        "accepted_stock_day_keys": full_keys + recovered_keys,
        "remaining_stock_day_gaps": missing_keys,
        "all_recovery_receipts_present": len(recovered) == len(missing),
        "market_modified": False,
        "production_merge_authorized": False,
    }
    logger("QMT_RECOVERY_SHA_REUSE_SUMMARY=" +
           json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["all_recovery_receipts_present"]:
        raise ValueError("Cannot skip QMT recovery: one or more verified receipts are missing")
    if missing_keys < 0:
        raise ValueError("Recovery receipt counts exceeded official DAY source keys")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("D:/stock"))
    args = p.parse_args(argv)
    verify(args.root)


if __name__ == "__main__":
    main()
