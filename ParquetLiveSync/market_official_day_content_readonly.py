#!/usr/bin/env python3
"""Read-only content validation of a SHA-bound declared single-day Parquet export.

Reuses market_quality_source_proofs for local file bytes. Does not establish
supplier identity, exchange calendar coverage, raw QMT provenance, or market
admission. Date/stock/period come from a validated explicit private manifest.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

STATUS = 'DECLARED_DAY_PARQUET_CONTENT_CHECKED_NOT_PROVIDER_AUTHENTICATED'
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')
COLS = ('ts', 'symbol') + FIELDS
MAX_ROWS = 100_000
CN = timezone(timedelta(hours=8))
EQUITY = re.compile(r'^(SH|SZ|BJ)[0-9]{6}$')
SUFFIX = re.compile(r'^([0-9]{6})[.:-](SH|SZ|BJ|XSHG|XSHE|BSE)$')


class DayContentError(ValueError):
    pass


def need(value, reason):
    if not value:
        raise DayContentError(reason)


def normal_symbol(raw):
    need(type(raw) is str, 'SYMBOL_NOT_TEXT')
    name = raw.strip().upper()
    if EQUITY.fullmatch(name):
        return name
    match = SUFFIX.fullmatch(name)
    if match:
        market = {'XSHG': 'SH', 'XSHE': 'SZ', 'BSE': 'BJ'}.get(match[2], match[2])
        return market + match[1]
    return None  # e.g. indexes, not evidence of an official equity day


def finite_number(x, name, *, positive=False):
    need(type(x) in (int, float), 'INVALID_' + name.upper())
    v = float(x)
    need(math.isfinite(v) and (v > 0 if positive else v >= 0),
         'NONFINITE_OR_INVALID_' + name.upper())
    return v


def validate_day_rows(rows, trading_day: str, target_symbol: str):
    """Pure streamed row check; whole-exchange completeness is NOT proven."""
    need(type(trading_day) is str and bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', trading_day)),
         'INVALID_TRADING_DAY')
    try:
        day = date.fromisoformat(trading_day)
    except ValueError as exc:
        raise DayContentError('INVALID_TRADING_DAY') from exc
    need(day.isoformat() == trading_day, 'INVALID_TRADING_DAY')
    need(type(target_symbol) is str and bool(EQUITY.fullmatch(target_symbol)),
         'INVALID_TARGET_SYMBOL')
    found = {}
    total = non_equities = 0
    for row in rows:
        total += 1
        need(total <= MAX_ROWS, 'DAY_EXPORT_ROW_LIMIT')
        need(isinstance(row, dict) and set(COLS).issubset(row), 'DAY_ROW_FIELDS_MISSING')
        ts = row['ts']
        need(type(ts) is int and 0 < ts < 4102444800000, 'DAY_TIMESTAMP_INVALID')
        try:
            actual_day = datetime.fromtimestamp(ts / 1000, tz=CN).date()
        except (ValueError, OverflowError, OSError) as exc:
            raise DayContentError('DAY_TIMESTAMP_INVALID') from exc
        need(actual_day == day, 'DAY_EXPORT_MIXED_OR_WRONG_DATES')
        symbol = normal_symbol(row['symbol'])
        if symbol is None:
            non_equities += 1
            continue
        need(symbol not in found, 'DUPLICATE_NORMALIZED_OFFICIAL_DAY_SYMBOL')
        vals = {key: finite_number(row[key], key, positive=key in FIELDS[:4])
                for key in FIELDS}
        need(vals['low'] <= min(vals['open'], vals['close'])
             and vals['high'] >= max(vals['open'], vals['close'])
             and vals['low'] <= vals['high'], 'DAY_OHLC_ENVELOPE_INVALID')
        need((vals['volume'] > 0) == (vals['amount'] > 0),
             'DAY_VOLUME_AMOUNT_PAIR_INCONSISTENT')
        found[symbol] = vals
    need(total > 0, 'DAY_EXPORT_EMPTY')
    need(target_symbol in found, 'TARGET_EQUITY_NOT_IN_DAY_EXPORT')
    data = found[target_symbol]
    need(data['volume'] > 0 and data['amount'] > 0,
         'TARGET_DAY_NOT_ACTIVE_TRADED_REFERENCE')
    return {
        'status': STATUS,
        'day': trading_day, 'target_symbol': target_symbol,
        'total_rows_examined': total,
        'unique_equity_symbols_validated': len(found),
        'non_equity_rows_not_used_for_stock_universe': non_equities,
        'target_ohlcva': data,
        'target_present_and_content_consistent': True,
        'complete_official_exchange_universe_certified': False,
        'official_provider_identity_authenticated': False,
        'source_independence_authenticated': False,
        'qmt_native_minute_data_certified': False,
        'market_candidate_validated': False,
        'market_admission_authorized': False,
        'market_files_written': False,
        'qmt_history_download_calls': 0,
    }


def _parquet_rows(path):
    """Use the existing schema contract; import pyarrow only at runtime."""
    import pyarrow.parquet as pq
    import local_layout as L
    reader = pq.ParquetFile(path)
    try:
        L.validate_schema(reader.schema_arrow)
        for batch in reader.iter_batches(batch_size=4096, columns=list(COLS), use_threads=False):
            for row in batch.to_pylist():
                yield row
    finally:
        reader.close()


def inspect(root: Path, relative_manifest: str, *, row_reader=None):
    """Validate declared file bytes both before and after content iteration."""
    import market_quality_source_proofs as P
    root = Path(root)
    before = P.verify(root, relative_manifest)
    doc_path = P._secure_relative(root, relative_manifest)
    # P.verify already rejects duplicate JSON keys and invalid manifest scope.
    with doc_path.open('r', encoding='utf-8-sig') as stream:
        manifest = json.load(stream, object_pairs_hook=P._pairs)
    scope = manifest['scope']
    need(scope['period'] == 'day', 'ONLY_DAY_PARQUET_CONTENT_SUPPORTED')
    day_item = next(i for i in manifest['artifacts'] if i['role'] == 'official_day')
    need(day_item['relative_path'].lower().endswith('.parquet'),
         'OFFICIAL_DAY_EXPECTED_PARQUET_EXPORT')
    file_path = P._secure_relative(root, day_item['relative_path'])
    load = row_reader or _parquet_rows
    content = validate_day_rows(load(file_path), scope['trading_day'], scope['symbol'])
    after = P.verify(root, relative_manifest)
    need(before == after, 'SOURCE_PROOF_CHANGED_DURING_CONTENT_CHECK')
    declared = next(x for x in before['artifacts'] if x['role'] == 'official_day')
    return {
        **content,
        'bound_official_day_file_bytes_sha256': declared['bytes_sha256'],
        'bound_source_manifest_bytes_sha256': before['manifest_bytes_sha256'],
        'source_file_bytes_verified': True,
        'content_check_scope': 'ONE_EXPLICIT_DAY_EXPORT_NOT_COMPLETE_MARKET_UNIVERSE',
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--manifest-relative', required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.evidence_root, a.manifest_relative),
                         ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (DayContentError, OSError, RuntimeError, ValueError, KeyError,
            TypeError, ImportError) as exc:
        print('MARKET_DAY_CONTENT_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
