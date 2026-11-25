#!/usr/bin/env python3
"""Read-only *application* diagnostic of the nine Nov25 QMT quarantines.

No download_history_data, no daily stage, no market file writes. Uses one
xtdata.get_market_data_ex (QMT may maintain its own internal cache/logs).
The returned bars are checked only in memory; even valid bars are not admitted.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys

RUN_DATE = '2026-11-25'
ORIGINAL_UPDATE_MARKET_BLOB = '2c510563ad387ab79188ca1d736b63496d187d1b'
RUN_SHA = '72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837'
SHAS = re.compile(r'[a-f0-9]{64}')
FIELDS = ['open', 'high', 'low', 'close', 'volume', 'amount']


class TriageError(ValueError):
    pass


def git_blob_sha(path):
    if path.is_symlink() or not path.is_file():
        raise TriageError('WRITER_SOURCE_MISSING_OR_SYMLINK')
    data = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def validate_source(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise TriageError('CANONICAL_MODULE_INVALID')
    path = root / 'update_market.py'
    if git_blob_sha(path) != ORIGINAL_UPDATE_MARKET_BLOB:
        raise TriageError('CANONICAL_MARKET_WRITER_BLOB_CHANGED_STOP')
    return root


def source_modules(module_root):
    # We deliberately load the canonical installed implementation; detached
    # audit worktrees contain no production work/state and must not be used.
    module_root = str(validate_source(module_root).resolve())
    sys.path.insert(0, module_root)
    update_market = importlib.import_module('update_market')
    if str(Path(update_market.__file__).resolve().parent) != module_root:
        raise TriageError('MODULE_IMPORT_NOT_CANONICAL')
    return update_market


def inspect_cache(report, payload, u, reference, day):
    if not isinstance(payload, dict):
        raise TriageError('QMT_BATCH_PAYLOAD_NOT_DICT')
    symbols = [x['symbol'] for x in report['stocks']]
    if len(symbols) != 9 or len(set(symbols)) != 9:
        raise TriageError('EXPECTED_EXACT_NINE_STOCKS')
    items = []
    for entry in report['stocks']:
        symbol = entry['symbol']
        code = symbol[2:] + '.' + symbol[:2]
        expected = reference.get(symbol)
        if not isinstance(expected, dict):
            raise TriageError('NO_INDEPENDENT_OFFICIAL_DAY_FOR_' + symbol)
        official = {f: float(expected[f]) for f in FIELDS}
        frame = payload.get(code)
        item = {'symbol': symbol, 'original_reason_category': entry['category'],
                'official_day_open': official['open'],
                'official_day_close': official['close'],
                'current_qmt_cache_status': '', 'raw_rows': None,
                'raw_first_open': None, 'validation_error': None,
                'data_repaired': False}
        if frame is None:
            item['current_qmt_cache_status'] = 'CACHE_KEY_MISSING'
        else:
            try:
                rows = u.P.normalize_frame(frame, code, day, day)
                item['raw_rows'] = len(rows)
                if not rows:
                    item['current_qmt_cache_status'] = 'CACHE_HAS_ZERO_ROWS'
                else:
                    item['raw_first_open'] = float(rows[0]['open'])
                    try:
                        # The actual purchased-feed calibration/grid/official
                        # OHLCVA acceptance code is reused IN MEMORY.
                        u.normal_qmt_day(rows, code, day, expected, u._audit_calibration)
                    except (ValueError, RuntimeError, TypeError, KeyError, OSError) as exc:
                        item['current_qmt_cache_status'] = 'CACHE_PRESENT_STILL_REJECTED'
                        item['validation_error'] = type(exc).__name__ + ': ' + str(exc)[:180]
                    else:
                        item['current_qmt_cache_status'] = 'CACHE_NOW_VALID_NOT_COMMITTED'
            except (ValueError, RuntimeError, TypeError, KeyError, OSError) as exc:
                item['current_qmt_cache_status'] = 'CACHE_FRAME_INVALID'
                item['validation_error'] = type(exc).__name__ + ': ' + str(exc)[:180]
        items.append(item)
    return {'status': 'READ_ONLY_QMT_CACHE_INSPECTION_NOT_REPAIR',
            'day': day.isoformat(), 'original_run_receipt_sha256': report['run_receipt_sha256'],
            'original_quarantine_count': len(items), 'source_reference_count': len(reference),
            'qmt_download_called': False, 'market_data_written': False,
            'internal_xtquant_side_effects_not_audited': True,
            'cached_now_valid': sum(x['current_qmt_cache_status'] == 'CACHE_NOW_VALID_NOT_COMMITTED' for x in items),
            'still_no_qmt_bars': sum(x['current_qmt_cache_status'] in ('CACHE_KEY_MISSING','CACHE_HAS_ZERO_ROWS') for x in items),
            'stocks': items}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--module-root', required=True, type=Path)
    ap.add_argument('--expected-run-sha256', default=RUN_SHA)
    ap.add_argument('--confirm-qmt-cache-query', action='store_true')
    args = ap.parse_args(argv)
    try:
        if not args.confirm_qmt_cache_query:
            raise TriageError('EXPLICIT_QMT_CACHE_QUERY_OPT_IN_REQUIRED')
        if args.expected_run_sha256 != RUN_SHA or not SHAS.fullmatch(args.expected_run_sha256):
            raise TriageError('EXACT_20261125_RECEIPT_SHA_REQUIRED')
        u = source_modules(args.module_root)
        from audit_market_quarantine_readonly import audit
        # Full physical-file SHA and stage receipt linkage BEFORE QMT usage.
        report = audit(args.module_root, RUN_DATE, RUN_SHA, verify_parquet=True)
        if report['quarantined'] != 9 or report['accepted'] != 5206:
            raise TriageError('UNEXPECTED_NINE_STOCK_EVIDENCE')
        target = date.fromisoformat(RUN_DATE)
        reference = u._reference_for_day(args.module_root.parent, target)
        if len(reference) != report['expected']:
            raise TriageError('OFFICIAL_DAY_STOCK_COUNT_CHANGED')
        for rec in report['stocks']:
            if rec['symbol'] not in reference:
                raise TriageError('OFFICIAL_DAY_SYMBOL_ABSENT')
        calibration = u.S._json(u.P.BASE / 'calibration' / 'latest.json')
        if calibration.get('calibration_passed') is not True or len(calibration.get('providers', {})) != 3:
            raise TriageError('PINNED_CALIBRATION_NOT_APPROVED')
        ledger = u.S._json(u.S.STATE_FILE)
        if ledger.get('qmt_calibration_sha256') != u.P.sha_bytes(u.P.canonical(calibration)):
            raise TriageError('PINNED_CALIBRATION_SHA_CHANGED')
        u._audit_calibration = calibration  # read-only in-memory only
        from xtquant import xtdata
        stocks = [record['symbol'][2:] + '.' + record['symbol'][:2] for record in report['stocks']]
        # Deliberately only the READ API; never call download_history_data.
        payload = xtdata.get_market_data_ex(
            field_list=FIELDS, stock_list=stocks, period='1m',
            start_time='20261125', end_time='20261125', count=-1,
            dividend_type='none', fill_data=False)
        print(json.dumps(inspect_cache(report, payload, u, reference, target),
                         indent=2, ensure_ascii=False))
        return 0
    except (TriageError, ValueError, OSError, ImportError, KeyError, TypeError) as exc:
        print('MARKET_QMT_CACHE_TRIAGE_REVIEW_REQUIRED: ' + str(exc)[:240])
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
