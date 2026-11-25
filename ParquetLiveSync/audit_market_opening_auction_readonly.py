#!/usr/bin/env python3
"""Replay 2026-11-25 opening-auction behavior for 2 QMT-quarantined stocks.

Explicit opt-in. One cached QMT read for 2 stocks; no history download,
no changes to any market or transaction state. xtquant may touch own cache/logs.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import sys

from audit_market_qmt_cache_readonly import (RUN_DATE, RUN_SHA, TriageError,
                                              git_blob_sha, source_modules)
from audit_market_quarantine_readonly import audit

STOCKS = ('SH605336', 'SZ300462')
FILES = ('open', 'high', 'low', 'close', 'volume', 'amount')
PINNED_MODULE_BLOBS = {
    'market_month_storage.py': '765d3bd9dc83cc146c98a965d1ac7a0d79042310',
    'qmt_1m_private_month_bridge.py': 'ba1f69a247aab18af8dbb547fdecc628ed9ee68c',
    'qmt_1m_pipeline.py': '73ebba2d2f03c86817ab7f8d658c26b1f7b3969c',
    'qmt_1m_probe.py': '3e2162f486c9d805497097722e2f5785c9bff9e1',
    'local_layout.py': 'e3b2b7b6900dae4dacfc9c1c2b339aee85e4e116',
    'live_sync.py': 'e209d471f129d94cf27b88283d2dbff89bd1a846',
}


def verify_dependencies(module_root: Path):
    """Require exact Git blobs; Git's Windows CRLF checkout is normalized."""
    for filename, pinned in PINNED_MODULE_BLOBS.items():
        if git_blob_sha(module_root / filename) != pinned:
            raise TriageError('CANONICAL_DEPENDENCY_CHANGED_' + filename.replace('.', '_'))


def _maybe_error(call):
    try:
        call()
        return None
    except (ValueError, RuntimeError, TypeError, KeyError, OSError) as exc:
        return type(exc).__name__ + ': ' + str(exc)[:220]


def replay_one(u, code, raw, expected, calibration, day: date):
    """Use the production _fold_241_day and normal_qmt_day, in memory only."""
    if len(raw) != 241:
        raise TriageError('EXPECTED_241_NATIVE_BARS_' + code)
    stamps = [datetime.fromisoformat(x['datetime_cn']) for x in raw]
    if any(x.utcoffset() != timedelta(hours=8) or x.date() != day for x in stamps):
        raise TriageError('NATIVE_TIMEZONE_OR_DATE_CHANGED_' + code)
    if ((stamps[0].hour, stamps[0].minute) != (9, 30)
            or (stamps[1].hour, stamps[1].minute) != (9, 31)):
        raise TriageError('NATIVE_FIRST_CLOCK_CHANGED_' + code)
    gate = u.B._calibration(calibration, code)
    offset = gate['offset_ms']
    if type(offset) is not int:
        raise TriageError('UNEXPECTED_OFFSET_' + code)
    original = [
        {'ts': u.P.stamp_ms(x['datetime_cn']) + offset,
         'symbol': u.L.normal_symbol(code),
         'open': float(x['open']), 'high': float(x['high']),
         'low': float(x['low']), 'close': float(x['close']),
         'volume': float(x['volume']) * gate['volume_factor'],
         'amount': float(x['amount']) * gate['amount_factor']}
        for x in raw
    ]
    # Production pure conversion; no temporary Parquet writer or source edit.
    converted, fold_kind = u.S._fold_241_day(original, offset, day.strftime('%Y-%m'))
    if len(converted) != 240:
        raise TriageError('FOLDED_240_LENGTH_CHANGED_' + code)
    fold_error = _maybe_error(lambda: u.verify_materialized_ohlc(converted, expected))
    full_error = _maybe_error(lambda: u.normal_qmt_day(raw, code, day, expected, calibration))
    # If the standalone fold disagrees with production's full normalization,
    # do NOT use it as forensic evidence of a root cause.
    if fold_error != full_error:
        raise TriageError('FOLD_AND_PRODUCTION_VALIDATION_DIVERGED_' + code)
    volume0930, amount0930 = float(raw[0]['volume']), float(raw[0]['amount'])
    if fold_kind not in ('REAL_AUCTION_FOLDED_TO_0931', 'ZERO_PLACEHOLDER'):
        raise TriageError('UNKNOWN_AUCTION_FOLD_KIND_' + code)
    if (fold_kind == 'REAL_AUCTION_FOLDED_TO_0931') != (volume0930 > 0 and amount0930 > 0):
        raise TriageError('AUCTION_KIND_UNEXPECTED_' + code)
    official_open = float(expected['open'])
    folded_open = float(converted[0]['open'])
    diff = folded_open - official_open
    threshold = max(.006 * max(abs(official_open), abs(folded_open)), .04)
    fits = math.isclose(folded_open, official_open, rel_tol=.006, abs_tol=.04)
    return {
        'symbol': u.L.normal_symbol(code),
        'date': day.isoformat(),
        'native_labels': len(raw),
        'folded_labels': len(converted),
        'auction_kind': fold_kind,
        'raw_0930_open': float(raw[0]['open']),
        'raw_0930_volume': volume0930,
        'raw_0930_amount': amount0930,
        'raw_0931_open': float(raw[1]['open']),
        'folded_0931_open': folded_open,
        'official_day_open': official_open,
        'folded_minus_official': round(diff, 10),
        'allowed_open_difference': round(threshold, 10),
        'open_isclose': fits,
        'official_day_close': float(expected['close']),
        'folded_day_close': float(converted[-1]['close']),
        'folded_ohlc_validation_error': fold_error,
        'full_original_validation_error': full_error,
        'all_data_changes_committed': False,
    }


def run_audit(module_root, *, confirm=False, xtdata=None, u=None, source_audit=audit):
    if not confirm:
        raise TriageError('EXPLICIT_TWO_STOCK_CACHE_QUERY_REQUIRED')
    module_root = Path(module_root)
    # Pin dependent source files BEFORE importing production dependencies.
    verify_dependencies(module_root)
    if u is None:
        u = source_modules(module_root)  # checks update_market.py blob
    else:
        # Real entrypoint never supplies a test u; preserve explicit source
        # check even if the caller passes an in-memory mock in tests.
        if not hasattr(u, 'P'):
            raise TriageError('MISSING_PINNED_UPDATER')
    report = source_audit(module_root, RUN_DATE, RUN_SHA, verify_parquet=True)
    original_mismatches = tuple(sorted(x['symbol'] for x in report['stocks']
                                      if x['category'] == 'OFFICIAL_DAY_OHLC_MISMATCH'))
    if (report['accepted'] != 5206 or report['quarantined'] != 9
            or report['expected'] != 5215 or original_mismatches != tuple(sorted(STOCKS))):
        raise TriageError('ORIGINAL_QUARANTINE_EVIDENCE_CHANGED')
    day = date.fromisoformat(RUN_DATE)
    reference = u._reference_for_day(module_root.parent, day)
    if len(reference) != 5215 or any(s not in reference for s in STOCKS):
        raise TriageError('OFFICIAL_DAY_REFERENCE_CHANGED')
    state = u.LIVE.read_state()
    original_day = state.get('days', {}).get(RUN_DATE)
    if not isinstance(original_day, dict) or not original_day.get('sha256'):
        raise TriageError('OFFICIAL_DAY_SOURCE_RECEIPT_MISSING')
    calibration = u.S._json(u.P.BASE / 'calibration' / 'latest.json')
    ledger = u.S._json(u.S.STATE_FILE)
    if (calibration.get('calibration_passed') is not True
            or len(calibration.get('providers', {})) != 3
            or ledger.get('qmt_calibration_sha256') != u.P.sha_bytes(u.P.canonical(calibration))):
        raise TriageError('OFFICIAL_PAID_CALIBRATION_CHANGED')
    if xtdata is None:
        from xtquant import xtdata
    codes = [s[2:] + '.' + s[:2] for s in STOCKS]
    payload = xtdata.get_market_data_ex(
        field_list=list(FILES), stock_list=codes, period='1m',
        start_time='20261125', end_time='20261125', count=-1,
        dividend_type='none', fill_data=False)
    if not isinstance(payload, dict):
        raise TriageError('QMT_CACHE_QUERY_NOT_DICT')
    results = []
    for s, code in zip(STOCKS, codes):
        frame = payload.get(code)
        if frame is None:
            raise TriageError('TWO_STOCK_CACHE_SYMBOL_NOT_RETURNED_' + s)
        rows = u.P.normalize_frame(frame, code, day, day)
        results.append(replay_one(u, code, rows, reference[s], calibration, day))
    return {
        'status': 'TWO_STOCK_OPENING_PROVENANCE_READ_ONLY_NOT_REPAIR',
        'original_run_sha256': RUN_SHA,
        'official_day_overlay_parquet_sha256': original_day['sha256'],
        'official_day_overlay_receipt_sha256': original_day.get('receipt_sha256'),
        'qmt_historical_download_called': False,
        'project_data_modified': False,
        'xtquant_cache_and_logs_side_effects_unverified': True,
        'data_quality_cleared': False,
        'stocks': results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--confirm-two-stock-cache-query', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run_audit(args.module_root, confirm=args.confirm_two_stock_cache_query)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (TriageError, ValueError, RuntimeError, TypeError, KeyError, OSError, ImportError) as exc:
        print('MARKET_OPENING_AUDIT_REVIEW_REQUIRED: ' + str(exc)[:220])
        return 3


if __name__ == '__main__':
    sys.exit(main())
