#!/usr/bin/env python3
"""Read-only bounded physical census of TWO existing QMT extra progress ledgers.

No QMT API, downloads, scheduled updates, data writes, replay or quarantine
admission. Ledgers are separate mutable checkpoints, not original-run evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

import qmt_extra_data as EXTRA
import qmt_extra_financial_cache_import as CACHE
import market_quality_source_proofs as PROOF

FORMAT = 'astock_finance_adjustment_progress_readonly_v1'
STATUS = 'LOCAL_FINANCE_ADJUSTMENT_PROGRESS_BYTES_ONLY_NOT_COMPLETENESS_CERTIFIED'
RELATIVE = ('progress.json', 'financial-cache-progress.json')
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class ProgressError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ProgressError(code)


def _identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode


def _date_or_empty(text):
    need(type(text) is str, 'PROGRESS_DATE_FIELD_INVALID')
    if text:
        need(bool(DAY_RE.fullmatch(text)), 'PROGRESS_DATE_FIELD_INVALID')
        try:
            need(date.fromisoformat(text).isoformat() == text,
                 'PROGRESS_DATE_FIELD_INVALID')
        except ValueError as exc:
            raise ProgressError('PROGRESS_DATE_FIELD_INVALID') from exc
    return text


def _code_or_empty(value):
    need(type(value) is str, 'PROGRESS_STOCK_CURSOR_INVALID')
    if value:
        try:
            need(EXTRA.valid_code(value) == value, 'PROGRESS_STOCK_CURSOR_INVALID')
        except ValueError as exc:
            raise ProgressError('PROGRESS_STOCK_CURSOR_INVALID') from exc
    return value


def _roots(module_root, stock_root):
    module = Path(module_root)
    need(module.is_dir() and not module.is_symlink(), 'MODULE_ROOT_UNSAFE')
    work = module / 'work'
    ledger_root = work / 'qmt_extra'
    need(work.is_dir() and not work.is_symlink()
         and ledger_root.is_dir() and not ledger_root.is_symlink(),
         'PROGRESS_LEDGER_DIRECTORY_MISSING_OR_LINKED')
    need(ledger_root.resolve().is_relative_to(work.resolve()),
         'PROGRESS_LEDGER_DIRECTORY_ESCAPE')
    stock = Path(stock_root)
    need(stock.is_dir() and not stock.is_symlink(), 'STOCK_ROOT_UNSAFE')
    try:
        actual = EXTRA._storage(stock)
    except (OSError, ValueError) as exc:
        raise ProgressError('STOCK_DATASET_LAYOUT_INVALID') from exc
    need(actual.is_dir() and not actual.is_symlink(),
         'STOCK_DATASET_EXTRA_DIRECTORY_UNAVAILABLE')
    return ledger_root, str(actual.resolve())


def _bytes(root, name):
    path = root / name
    need(not path.is_symlink(), 'PROGRESS_LEDGER_SYMLINK_FORBIDDEN')
    if not path.exists():
        return None
    need(path.is_file(), 'PROGRESS_LEDGER_NOT_REGULAR')
    before = os.stat(path, follow_symlinks=False)
    need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_FILE_BYTES,
         'PROGRESS_LEDGER_EMPTY_OR_SIZE_LIMIT')
    try:
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            need(_identity(opened) == _identity(before),
                 'PROGRESS_LEDGER_CHANGED_DURING_READ')
            data = stream.read(MAX_FILE_BYTES + 1)
            closed = os.fstat(stream.fileno())
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ProgressError('PROGRESS_LEDGER_READ_FAILED') from exc
    need(0 < len(data) <= MAX_FILE_BYTES
         and len(data) == before.st_size
         and _identity(before) == _identity(opened)
         == _identity(closed) == _identity(after)
         and not path.is_symlink(),
         'PROGRESS_LEDGER_CHANGED_DURING_READ')
    try:
        value = json.loads(data.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as exc:
        raise ProgressError('PROGRESS_LEDGER_INVALID_JSON') from exc
    need(type(value) is dict, 'PROGRESS_LEDGER_NOT_OBJECT')
    return {'path': path, 'identity': _identity(before),
            'sha256': sha256(data).hexdigest(), 'bytes': len(data),
            'data': value}


def _supplementary(v, expected_root):
    need(v.get('format') == EXTRA.FORMAT and
         v.get('root') == expected_root and
         type(v.get('cursor')) is dict,
         'SUPPLEMENTARY_LEDGER_IDENTITY_INVALID')
    cursors = v['cursor']
    for key, value in cursors.items():
        need(type(key) is str and type(value) is str,
             'SUPPLEMENTARY_LEDGER_CURSOR_INVALID')
        if key in ('financial', 'adjustments'):
            _code_or_empty(value)
    pending = v.get('financial_pending', {})
    need(type(pending) is dict and len(pending) <= 10000,
         'SUPPLEMENTARY_PENDING_MALFORMED')
    tables = Counter()
    for code, entry in pending.items():
        _code_or_empty(code)
        need(type(entry) is dict and
             entry.get('table') in EXTRA.FIN_TABLES and
             type(entry.get('attempts')) is int and entry['attempts'] >= 1,
             'SUPPLEMENTARY_PENDING_MALFORMED')
        tables[entry['table']] += 1
    asof = v.get('last_asof')
    if asof is not None and type(asof) is str:
        _date_or_empty(asof)
    elif asof is not None and type(asof) is not dict:
        raise ProgressError('SUPPLEMENTARY_LAST_ASOF_INVALID')
    return {
        'present': True, 'financial_cursor': cursors.get('financial', ''),
        'adjustments_cursor': cursors.get('adjustments', ''),
        'financial_pending_count': len(pending),
        'financial_pending_by_table': dict(sorted(tables.items())),
        'last_asof_label': asof if type(asof) is str else None,
        'cursor_values_do_not_prove_remaining_universe': True,
    }


def _cache(v, expected_root):
    need(v.get('format') == CACHE.FORMAT and
         v.get('root') == expected_root and
         type(v.get('pending')) is dict and
         type(v.get('import_cursor')) is str and
         type(v.get('daily_cursor')) is str and
         type(v.get('daily_date')) is str and
         type(v.get('pending_retry_cursor', '')) is str and
         type(v.get('daily_sweep_reached_end', False)) is bool,
         'FINANCIAL_CACHE_LEDGER_IDENTITY_INVALID')
    for key in ('daily_date', 'daily_sweep_start', 'daily_sweep_finished'):
        _date_or_empty(v.get(key, ''))
    for key in ('import_cursor', 'daily_cursor', 'pending_retry_cursor'):
        _code_or_empty(v.get(key, ''))
    pending = v['pending']
    need(len(pending) <= 10000, 'FINANCIAL_PENDING_BUDGET')
    reasons = Counter()
    for code, entry in pending.items():
        _code_or_empty(code)
        need(type(entry) is dict and
             entry.get('reason') in
             ('NO_CACHE', 'SOURCE_HISTORY_CONFLICT', 'CACHE_DECODE_ERROR') and
             type(entry.get('attempts')) is int and entry['attempts'] >= 1,
             'FINANCIAL_PENDING_ENTRY_INVALID')
        reasons[entry['reason']] += 1
    return {
        'present': True,
        'daily_date': v['daily_date'],
        'daily_cursor': v['daily_cursor'],
        'daily_sweep_start': v.get('daily_sweep_start', ''),
        'daily_sweep_reached_end': v.get('daily_sweep_reached_end', False),
        'daily_sweep_finished': v.get('daily_sweep_finished', ''),
        'import_cursor': v['import_cursor'],
        'pending_retry_cursor': v.get('pending_retry_cursor', ''),
        'pending_count': len(pending),
        'pending_reason_counts': dict(sorted(reasons.items())),
        'remaining_unvisited_unknown_without_original_universe': True,
    }


def inspect(module_root, stock_root):
    directory, expected_root = _roots(module_root, stock_root)
    before_dir = _identity(os.stat(directory, follow_symlinks=False))
    ledger_a = _bytes(directory, RELATIVE[0])
    ledger_b = _bytes(directory, RELATIVE[1])
    observed = [x for x in (ledger_a, ledger_b) if x is not None]
    need(sum(x['bytes'] for x in observed) <= MAX_TOTAL_BYTES,
         'PROGRESS_TOTAL_BYTES_LIMIT')
    # Parse actual physical byte snapshots. Missing is not an empty/default state.
    supplementary = (_supplementary(ledger_a['data'], expected_root)
                     if ledger_a else {'present': False})
    cache = (_cache(ledger_b['data'], expected_root)
             if ledger_b else {'present': False})
    # Rehash each physical file, including its identity and bytes, then make
    # sure previously missing entries remain missing. No lock is claimed.
    for name, item in zip(RELATIVE, (ledger_a, ledger_b)):
        again = _bytes(directory, name)
        if item is None:
            need(again is None, 'PROGRESS_LEDGER_APPEARED_DURING_CHECK')
        else:
            need(again is not None
                 and again['sha256'] == item['sha256']
                 and again['identity'] == item['identity']
                 and again['bytes'] == item['bytes'],
                 'PROGRESS_LEDGER_CHANGED_DURING_CHECK')
    need(_identity(os.stat(directory, follow_symlinks=False)) == before_dir,
         'PROGRESS_DIRECTORY_CHANGED_DURING_CHECK')
    return {
        'format': FORMAT, 'status': STATUS,
        'checkpoint_directory_relative_to_module': 'work/qmt_extra',
        'ledgers_present': len(observed),
        'ledgers_expected': len(RELATIVE),
        'physical_ledgers': [
            {'name': name, 'present': item is not None,
             'sha256': item['sha256'] if item else None,
             'bytes': item['bytes'] if item else None}
            for name, item in zip(RELATIVE, (ledger_a, ledger_b))],
        'supplementary_progress': supplementary,
        'financial_cache_progress': cache,
        'separate_progress_ledgers_not_aggregated': True,
        '20261125_report_is_historical_not_current_state': True,
        'state_cross_file_atomic_snapshot_certified': False,
        'finance_full_history_coverage_certified': False,
        'adjustments_universe_exhaustion_certified': False,
        'official_market_source_authenticated': False,
        'original_run_receipt_authenticated': False,
        'original_quarantines_cleared': False,
        'market_files_written': False,
        'qmt_cache_queried_or_modified': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    p.add_argument('--stock-root', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.module_root, a.stock_root),
                         ensure_ascii=False, indent=2,
                         sort_keys=True, allow_nan=False))
        return 0
    except (ProgressError, PROOF.ProofError, ValueError,
            OSError, TypeError, OverflowError, RuntimeError) as exc:
        # Do not emit private absolute path, a provider exception or raw JSON.
        print('LOCAL_PROGRESS_READONLY_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
