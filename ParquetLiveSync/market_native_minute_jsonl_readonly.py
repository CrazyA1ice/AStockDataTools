#!/usr/bin/env python3
"""Read-only SHA-pinned content audit for existing QMT-probe-style JSONL.

Local byte/row/grid evidence is not proof of QMT origin, calibration, official
stock-day membership, minute repair, a production backup or write authority.
No QMT SDK, filesystem writes, downloads or Arrow imports are used here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import re

import market_quality_source_proofs as PROOF

FORMAT = 'astock_declared_native_minute_jsonl_readonly_v1'
STATUS = 'LOCAL_MINUTE_JSONL_CONTENT_CHECKED_QMT_ORIGIN_UNAUTHENTICATED'
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')
ROW_KEYS = frozenset(('datetime_cn', 'symbol') + FIELDS)
SYMBOL = re.compile(r'^(?:[0-9]{6}\.(?:SH|SZ)|(?:SH|SZ)[0-9]{6})$')
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MAX_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 8192
MAX_ROWS = 20000
MAX_WINDOW_DAYS = 64
CN_OFFSET = timedelta(hours=8)
GRID = frozenset(
    [(h, m) for h in (9, 10, 11, 13, 14, 15) for m in range(60)
     if (h == 9 and m >= 30) or h == 10 or (h == 11 and m <= 30)
     or (h == 13 and m >= 1) or h == 14 or (h == 15 and m == 0)]
)
GRID_240 = GRID - {(9, 30)}


class NativeMinuteError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise NativeMinuteError(reason)


def normalize_symbol(value):
    need(type(value) is str and bool(SYMBOL.fullmatch(value)), 'MINUTE_SYMBOL_INVALID')
    return (value[2:] + '.' + value[:2]) if value[:2] in ('SH', 'SZ') else value


def parse_day(value):
    need(type(value) is str and bool(DAY.fullmatch(value)), 'MINUTE_DAY_INVALID')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise NativeMinuteError('MINUTE_DAY_INVALID') from exc
    need(parsed.isoformat() == value, 'MINUTE_DAY_INVALID')
    return parsed


def strict_pairs(pairs):
    out = {}
    for key, val in pairs:
        need(key not in out, 'MINUTE_JSON_DUPLICATE_KEY')
        out[key] = val
    return out


def reject_constant(value):
    raise NativeMinuteError('MINUTE_JSON_NONFINITE_CONSTANT')


def parse_line(raw):
    try:
        item = json.loads(raw.decode('utf-8'), object_pairs_hook=strict_pairs,
                          parse_constant=reject_constant)
    except NativeMinuteError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise NativeMinuteError('MINUTE_JSONL_INVALID') from exc
    need(type(item) is dict and set(item) == ROW_KEYS, 'MINUTE_JSONL_ROW_SCHEMA_INVALID')
    return item


def parse_stamp(value):
    need(type(value) is str and len(value) <= 48, 'MINUTE_TIMESTAMP_INVALID')
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise NativeMinuteError('MINUTE_TIMESTAMP_INVALID') from exc
    need(stamp.tzinfo is not None and stamp.utcoffset() == CN_OFFSET and
         stamp.isoformat() == value and stamp.second == 0 and stamp.microsecond == 0,
         'MINUTE_TIMESTAMP_NOT_CANONICAL_CN_MINUTE')
    return stamp


def finite_field(value, field):
    need(type(value) in (int, float), 'MINUTE_' + field.upper() + '_TYPE_INVALID')
    try:
        converted = float(value)
    except (ValueError, OverflowError) as exc:
        raise NativeMinuteError('MINUTE_' + field.upper() + '_INVALID') from exc
    need(math.isfinite(converted) and
         (converted > 0 if field in FIELDS[:4] else converted >= 0),
         'MINUTE_' + field.upper() + '_INVALID')
    return converted


def check_rows(rows, *, target_symbol, target_day, start_day, end_day):
    """Read and validate every row; only the selected day receives grid status."""
    symbol = normalize_symbol(target_symbol)
    target = parse_day(target_day)
    start, end = parse_day(start_day), parse_day(end_day)
    need(start <= target <= end and (end - start).days < MAX_WINDOW_DAYS,
         'MINUTE_REQUEST_WINDOW_INVALID')
    total, previous, days, target_items = 0, None, Counter(), []
    for row in rows:
        total += 1
        need(total <= MAX_ROWS, 'MINUTE_JSONL_ROW_BUDGET_EXCEEDED')
        need(type(row) is dict and set(row) == ROW_KEYS, 'MINUTE_JSONL_ROW_SCHEMA_INVALID')
        need(normalize_symbol(row['symbol']) == symbol,
             'MINUTE_EXPORT_MIXED_OR_WRONG_SYMBOL')
        stamp = parse_stamp(row['datetime_cn'])
        need(start <= stamp.date() <= end, 'MINUTE_EXPORT_OUTSIDE_DECLARED_WINDOW')
        label = (stamp.hour, stamp.minute)
        need(label in GRID, 'MINUTE_TIMESTAMP_OUTSIDE_NATIVE_GRID')
        need(previous is None or stamp > previous,
             'MINUTE_JSONL_UNSORTED_OR_DUPLICATE_TIMESTAMP')
        previous = stamp
        values = {field: finite_field(row[field], field) for field in FIELDS}
        need(values['low'] <= min(values['open'], values['close']) and
             values['high'] >= max(values['open'], values['close']) and
             values['low'] <= values['high'], 'MINUTE_OHLC_ENVELOPE_INVALID')
        need((values['volume'] > 0) == (values['amount'] > 0),
             'MINUTE_VOLUME_AMOUNT_PAIR_INVALID')
        days[stamp.date().isoformat()] += 1
        if stamp.date() == target:
            target_items.append((label, values))
    need(total > 0, 'MINUTE_EXPORT_EMPTY')
    labels = [label for label, _ in target_items]
    full = len(labels) == 241 and set(labels) == GRID
    without_open = len(labels) == 240 and set(labels) == GRID_240
    need(full or without_open, 'TARGET_MINUTE_GRID_NOT_EXACT_241_OR_240')
    values = [v for _, v in target_items]
    sums = {field: math.fsum(v[field] for v in values)
            for field in ('volume', 'amount')}
    need(all(math.isfinite(v) for v in sums.values()), 'MINUTE_AGGREGATE_NONFINITE')
    return {
        'format': FORMAT, 'status': STATUS,
        'declared_symbol': symbol,
        'declared_window': [start.isoformat(), end.isoformat()],
        'target_day': target.isoformat(),
        'file_records_structurally_checked': total,
        'observed_file_days': len(days),
        'other_day_records_not_grid_certified': total - len(target_items),
        'target_minute_rows': len(target_items),
        'target_native_grid_classification':
            'EXACT_241_WITH_0930' if full else 'EXACT_240_WITHOUT_0930_REVIEW_REQUIRED',
        'opening_0930_observed': full,
        'exact_241_native_labels_observed': full,
        'exact_240_without_opening_labels_observed': without_open,
        'raw_uncalibrated_target_ohlcva': {
            'open': values[0]['open'],
            'high': max(v['high'] for v in values),
            'low': min(v['low'] for v in values),
            'close': values[-1]['close'],
            **sums,
        },
        'provider_origin_authenticated': False,
        'minute_adjustment_and_paid_units_calibrated': False,
        'official_stock_day_universe_certified': False,
        'six_field_official_day_reconciliation_passed': False,
        'eight_period_aggregation_validated': False,
        'production_quarantine_cleared': False,
        'production_merge_authorized': False,
        'market_files_written': False,
        'qmt_download_calls': 0,
    }


def _file_rows(path):
    with path.open('rb') as stream:
        for line in stream:
            need(0 < len(line) <= MAX_LINE_BYTES, 'MINUTE_JSONL_LINE_LIMIT')
            need(bool(line.strip()), 'MINUTE_JSONL_EMPTY_LINE')
            yield parse_line(line)


def inspect(root, relative, expected_sha256, target_symbol, target_day,
            start_day, end_day, *, row_reader=None):
    """Check physical JSONL SHA before/after reading bounded local rows."""
    need(type(expected_sha256) is str and bool(PROOF.HEX64.fullmatch(expected_sha256)),
         'MINUTE_EXPECTED_SHA_INVALID')
    need(type(relative) is str and relative.lower().endswith('.jsonl'),
         'MINUTE_JSONL_EXTENSION_REQUIRED')
    root = Path(root)
    need(root.is_dir() and not root.is_symlink(), 'MINUTE_EVIDENCE_ROOT_INVALID')
    path = PROOF._secure_relative(root, relative)
    before_stat = path.stat()
    need(0 < before_stat.st_size <= MAX_BYTES, 'MINUTE_JSONL_BYTE_BUDGET_EXCEEDED')
    before_sha, before_size = PROOF._hash_stable_file(path)
    need(before_sha == expected_sha256.lower() and before_size == before_stat.st_size,
         'MINUTE_JSONL_SOURCE_BYTES_SHA_CHANGED')
    reader = row_reader or _file_rows
    report = check_rows(reader(path), target_symbol=target_symbol,
                        target_day=target_day, start_day=start_day, end_day=end_day)
    after_sha, after_size = PROOF._hash_stable_file(path)
    after_stat = path.stat()
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    need(before_sha == after_sha and before_size == after_size and
         identity(before_stat) == identity(after_stat),
         'MINUTE_JSONL_SOURCE_CHANGED_DURING_CONTENT_READ')
    report.update({
        'physical_local_source_file_sha256': before_sha,
        'physical_local_source_file_bytes': before_size,
        'source_file_bytes_verified': True,
        'source_sha_is_not_independent_qmt_signature': True,
        'file_scope': 'EXPLICIT_LOCAL_PROBE_STYLE_JSONL_ONLY',
    })
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--file-relative', required=True)
    parser.add_argument('--expected-file-sha256', required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--target-day', required=True)
    parser.add_argument('--start-day', required=True)
    parser.add_argument('--end-day', required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect(args.evidence_root, args.file_relative,
                         args.expected_file_sha256, args.symbol,
                         args.target_day, args.start_day, args.end_day)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False))
        return 0
    except (NativeMinuteError, PROOF.ProofError, ValueError, TypeError,
            OSError, OverflowError, ImportError) as exc:
        # Private evidence path and market data never enter failure stdout.
        print('NATIVE_MINUTE_LOCAL_JSONL_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
