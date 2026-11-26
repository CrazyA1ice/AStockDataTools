#!/usr/bin/env python3
"""Read-only bounded date-window clock census of an existing SHA-pinned probe JSONL.

The source is a local byte claim, not an authenticated QMT provenance chain.
Missing calendar days are not proven missing *trading* days. Never repair data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import json
from pathlib import Path

import market_native_minute_jsonl_readonly as M
import market_quality_source_proofs as P

FORMAT = 'astock_native_minute_window_grid_readonly_v1'
STATUS = 'LOCAL_PROBE_JSONL_DATE_WINDOW_GRID_CENSUS_NOT_NATIVE_SOURCE_AUTHENTICATED'
MAX_MISSING_SAMPLES = 5


class WindowError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise WindowError(reason)


def _identity(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def inspect(root, relative, expected_sha256, symbol, start_day, end_day, *, row_reader=None):
    """Verify all physical bytes/rows and census each calendar date, no writes."""
    normal = M.normalize_symbol(symbol)
    first_day, last_day = M.parse_day(start_day), M.parse_day(end_day)
    need(first_day <= last_day and (last_day-first_day).days < M.MAX_WINDOW_DAYS,
         'WINDOW_INVALID_OR_EXCEEDS_BUDGET')
    need(type(relative) is str and relative.lower().endswith('.jsonl'),
         'WINDOW_JSONL_EXTENSION_REQUIRED')
    need(type(expected_sha256) is str and bool(P.HEX64.fullmatch(expected_sha256)),
         'WINDOW_EXPECTED_SHA_INVALID')
    root = Path(root)
    need(root.is_dir() and not root.is_symlink(), 'WINDOW_ROOT_INVALID')
    path = P._secure_relative(root, relative)
    before = _identity(path)
    need(0 < before[2] <= M.MAX_BYTES, 'WINDOW_FILE_SIZE_LIMIT')
    actual, byte_count = P._hash_stable_file(path)
    need(byte_count == before[2] and byte_count <= M.MAX_BYTES and
         actual == expected_sha256.lower(), 'WINDOW_SOURCE_SHA_MISMATCH')

    labels = defaultdict(list)
    examined = 0

    def monitored_rows():
        nonlocal examined
        for row in (row_reader or M._file_rows)(path):
            examined += 1
            need(examined <= M.MAX_ROWS, 'WINDOW_ROW_COUNT_LIMIT')
            # The underlying P3.5 validator checks types, timezone, OHLCVA,
            # order, same-symbol scope, and exchange clock for ALL rows.
            if type(row) is dict and type(row.get('datetime_cn')) is str:
                clock = row['datetime_cn']
                labels[clock[:10]].append(clock[11:16])
            yield row

    # The selected start date may be a non-trading day. P3.5 validates every
    # row before the sole target grid check; only that exact final failure may
    # be softened to permit a calendar window with no rows on some dates.
    try:
        M.check_rows(monitored_rows(), target_symbol=normal, target_day=start_day,
                     start_day=start_day, end_day=end_day)
    except M.NativeMinuteError as exc:
        if str(exc) != 'TARGET_MINUTE_GRID_NOT_EXACT_241_OR_240':
            raise
    need(examined > 0, 'WINDOW_JSONL_NO_ROWS')
    expected_full = {f'{h:02}:{m:02}' for h,m in M.GRID}
    expected_240 = {f'{h:02}:{m:02}' for h,m in M.GRID_240}
    days, statuses = [], Counter()
    count_day = (last_day - first_day).days + 1
    for offset in range(count_day):
        day = (first_day + timedelta(days=offset)).isoformat()
        observed = labels.get(day, [])
        present = set(observed)
        if not observed:
            status = 'NO_ROWS_CALENDAR_DAY_NOT_PROVED_TRADING'
        elif len(observed) == 241 and present == expected_full:
            status = 'EXACT_241_WITH_0930'
        elif len(observed) == 240 and present == expected_240:
            status = 'EXACT_240_WITHOUT_0930_REVIEW_REQUIRED'
        else:
            status = 'PARTIAL_NATIVE_GRID_REVIEW_REQUIRED'
        statuses[status] += 1
        days.append({
            'day': day,
            'rows': len(observed),
            'grid_status': status,
            'opening_0930_present': '09:30' in present,
            'missing_native_labels_count': 241 - len(present),
            'missing_native_labels_examples': sorted(expected_full-present)[:MAX_MISSING_SAMPLES],
            'trading_day_independently_certified': False,
            'qmt_source_authenticated': False,
            'production_repair_authorized': False,
        })
    need(sum(d['rows'] for d in days) == examined, 'WINDOW_ROW_CONSERVATION_FAILED')
    # Re-hash actual local evidence after streaming, then verify stable inode,
    # size and mtime. Does not confer a filesystem lock or provider signature.
    final_sha, final_bytes = P._hash_stable_file(path)
    need(final_sha == actual and final_bytes == byte_count and
         _identity(path) == before and
         P._secure_relative(root, relative) == path,
         'WINDOW_FILE_CHANGED_DURING_AUDIT')
    return {
        'format': FORMAT, 'status': STATUS,
        'declared_symbol': normal,
        'declared_window': [first_day.isoformat(), last_day.isoformat()],
        'physical_local_file_sha256': actual,
        'physical_local_file_bytes': byte_count,
        'source_file_bytes_verified': True,
        'rows_structurally_and_numerically_validated': examined,
        'calendar_days_examined': count_day,
        'grid_status_counts': dict(sorted(statuses.items())),
        'days': days,
        'all_observed_days_exact_241': all(d['grid_status'] == 'EXACT_241_WITH_0930'
                                           for d in days if d['rows'] > 0),
        'official_exchange_calendar_or_stock_universe_certified': False,
        'native_qmt_provider_origin_authenticated': False,
        'purchased_minute_units_or_offset_calibrated': False,
        'six_field_official_day_reconciliation_passed': False,
        'eight_period_aggregation_validated': False,
        'production_quarantine_cleared': False,
        'market_candidate_validated': False,
        'production_merge_authorized': False,
        'market_files_written': False,
        'qmt_cache_modified': False,
        'qmt_history_download_calls': 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', required=True, type=Path)
    p.add_argument('--file-relative', required=True)
    p.add_argument('--expected-file-sha256', required=True)
    p.add_argument('--symbol', required=True)
    p.add_argument('--start-day', required=True)
    p.add_argument('--end-day', required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.evidence_root, a.file_relative,
                                 a.expected_file_sha256, a.symbol,
                                 a.start_day, a.end_day),
                         ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False))
        return 0
    except (WindowError, M.NativeMinuteError, P.ProofError, ValueError,
            OSError, TypeError, OverflowError, RuntimeError) as exc:
        print('MINUTE_WINDOW_GRID_CENSUS_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
