#!/usr/bin/env python3
"""Diagnose raw six-field differences between separately SHA-pinned local files.

Pairs an existing probe-style QMT JSONL with a declared DAY Parquet file.
Neither source is supplier-authenticated. No paid-unit/offset calibration,
production eligibility, market writes, QMT cache access or download happens.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path

import market_native_minute_jsonl_readonly as MINUTE
import market_official_day_content_readonly as DAY
import market_quality_source_proofs as PROOF

FORMAT = 'astock_raw_minute_declared_day_pair_readonly_v1'
STATUS = 'PHYSICAL_MINUTE_DAY_PAIR_RAW_DIFFERENCES_NOT_CALIBRATED'
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')


class PairError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise PairError(reason)


def _identity(root, relative):
    """Do not accept a file alias masquerading as an independent input."""
    root = Path(root)
    need(root.is_dir() and not root.is_symlink(), 'PAIR_EVIDENCE_ROOT_INVALID')
    path = PROOF._secure_relative(root, relative)
    st = path.stat()
    return path, (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _day_symbol(qmt_symbol):
    normal = MINUTE.normalize_symbol(qmt_symbol)
    return normal[-2:] + normal[:6]


def _strict_ohlcva(rows, name):
    need(type(rows) is dict and set(rows) == set(FIELDS), name + '_FIELDS_INVALID')
    values = {}
    for key in FIELDS:
        val = rows[key]
        need(type(val) in (int, float), name + '_NON_NUMERIC_' + key.upper())
        try:
            n = float(val)
        except (ValueError, OverflowError) as exc:
            raise PairError(name + '_NONFINITE_' + key.upper()) from exc
        need(math.isfinite(n) and (n > 0 if key in FIELDS[:4] else n >= 0),
             name + '_NONFINITE_' + key.upper())
        values[key] = n
    return values


def _validate_receipts(m, d, symbol, day):
    need(type(m) is dict and m.get('status') == MINUTE.STATUS and
         m.get('format') == MINUTE.FORMAT and m.get('declared_symbol') == symbol and
         m.get('target_day') == day and m.get('source_file_bytes_verified') is True and
         m.get('provider_origin_authenticated') is False and
         m.get('minute_adjustment_and_paid_units_calibrated') is False and
         m.get('six_field_official_day_reconciliation_passed') is False and
         m.get('production_merge_authorized') is False and
         m.get('market_files_written') is False and
         m.get('qmt_download_calls') == 0 and
         m.get('target_native_grid_classification') in
         ('EXACT_241_WITH_0930', 'EXACT_240_WITHOUT_0930_REVIEW_REQUIRED') and
         type(m.get('target_minute_rows')) is int and
         m['target_minute_rows'] in (240, 241),
         'MINUTE_SOURCE_REPORT_SCOPE_OR_AUTHORITY_INVALID')
    need((m['target_minute_rows'] == 241) ==
         (m['target_native_grid_classification'] == 'EXACT_241_WITH_0930'),
         'MINUTE_GRID_COUNT_CLASSIFICATION_CONFLICT')
    need(type(d) is dict and d.get('status') == DAY.STATUS and
         d.get('day') == day and d.get('target_symbol') == _day_symbol(symbol) and
         d.get('source_file_bytes_verified') is True and
         d.get('official_provider_identity_authenticated') is False and
         d.get('source_independence_authenticated') is False and
         d.get('qmt_native_minute_data_certified') is False and
         d.get('market_admission_authorized') is False and
         d.get('market_files_written') is False and
         d.get('qmt_history_download_calls') == 0,
         'DAY_SOURCE_REPORT_SCOPE_OR_AUTHORITY_INVALID')
    need(all(type(x.get(k)) is str and PROOF.HEX64.fullmatch(x[k])
             for x,k in ((m, 'physical_local_source_file_sha256'),
                         (d, 'bound_official_day_file_bytes_sha256'))),
         'SOURCE_PAIR_SHA_MISSING')
    return (_strict_ohlcva(m.get('raw_uncalibrated_target_ohlcva'), 'MINUTE'),
            _strict_ohlcva(d.get('target_ohlcva'), 'DAY'))


def inspect(minute_root, minute_relative, minute_sha256, day_root, day_relative,
            day_sha256, symbol, target_day, start_day, end_day,
            *, minute_row_reader=None, day_row_reader=None):
    """Read actual byte sources and report arithmetic deltas without passing gates."""
    normalized = MINUTE.normalize_symbol(symbol)
    MINUTE.parse_day(target_day)
    mpath, mstat = _identity(minute_root, minute_relative)
    dpath, dstat = _identity(day_root, day_relative)
    need((mstat[0], mstat[1]) != (dstat[0], dstat[1]) and
         mpath.resolve() != dpath.resolve(), 'PAIR_SAME_PHYSICAL_SOURCE_FILE')
    m = MINUTE.inspect(minute_root, minute_relative, minute_sha256, normalized,
                       target_day, start_day, end_day, row_reader=minute_row_reader)
    d = DAY.inspect_explicit(day_root, day_relative, day_sha256, target_day,
                             _day_symbol(normalized), row_reader=day_row_reader)
    mv, dv = _validate_receipts(m, d, normalized, target_day)
    need(m['physical_local_source_file_sha256'] == minute_sha256.lower() and
         d['bound_official_day_file_bytes_sha256'] == day_sha256.lower(),
         'SOURCE_PAIR_REPORT_HASH_CHANGED')
    differences = {}
    for field in FIELDS:
        diff = mv[field] - dv[field]
        relative = diff / max(abs(dv[field]), 1e-12)
        need(math.isfinite(diff) and math.isfinite(relative),
             'RAW_DIAGNOSTIC_NUMERIC_OVERFLOW')
        differences[field] = {'minute_uncalibrated': mv[field],
                              'day_declared_reference': dv[field],
                              'raw_signed_difference': diff,
                              'raw_relative_difference': relative}
    # A final paired rehash narrows but does not eliminate the TOCTOU window.
    ma, mb = PROOF._hash_stable_file(mpath)
    da, db = PROOF._hash_stable_file(dpath)
    need(ma == minute_sha256.lower() and da == day_sha256.lower() and
         mb == mstat[2] and db == dstat[2] and
         mstat == _identity(minute_root, minute_relative)[1] and
         dstat == _identity(day_root, day_relative)[1],
         'SOURCE_PAIR_CHANGED_BEFORE_FINAL_REPORT')
    pair_scope = {'symbol': normalized, 'day': target_day,
                  'minute_sha256': ma, 'day_sha256': da,
                  'minute_grid': m['target_native_grid_classification']}
    pair_sha = sha256(json.dumps(pair_scope, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    return {
        'format': FORMAT, 'status': STATUS, 'target_day': target_day,
        'target_symbol': normalized, 'source_pair_diagnostic_sha256': pair_sha,
        'minute_local_bytes_sha256': ma, 'day_local_bytes_sha256': da,
        'minute_local_file_bytes': mb, 'day_local_file_bytes': db,
        'minute_grid': m['target_native_grid_classification'],
        'minute_count': m['target_minute_rows'],
        'field_raw_differences_not_calibrated': differences,
        'all_six_fields_raw_computed': True,
        'provider_independence_or_identity_authenticated': False,
        'qmt_native_origin_authenticated': False,
        'minute_paid_scale_or_timestamp_calibrated': False,
        'six_field_comparison_quality_passed': False,
        'official_stock_day_universe_certified': False,
        'eight_period_recalculation_verified': False,
        'producer_quarantine_closed': False,
        'market_candidate_validated': False,
        'backup_materialized': False,
        'physical_source_lock_held': False,
        'production_merge_authorized': False,
        'market_files_written': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('minute-evidence-root', 'minute-file-relative',
                 'expected-minute-sha256', 'day-evidence-root', 'day-file-relative',
                 'expected-day-sha256', 'symbol', 'target-day',
                 'minute-start-day', 'minute-end-day'):
        parser.add_argument('--' + name, required=True)
    a = parser.parse_args(argv)
    try:
        r = inspect(a.minute_evidence_root, a.minute_file_relative,
                    a.expected_minute_sha256, a.day_evidence_root,
                    a.day_file_relative, a.expected_day_sha256, a.symbol,
                    a.target_day, a.minute_start_day, a.minute_end_day)
        print(json.dumps(r, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False))
        return 0
    except (PairError, MINUTE.NativeMinuteError, DAY.DayContentError,
            PROOF.ProofError, ValueError, TypeError, OSError, OverflowError,
            ImportError, KeyError) as exc:
        # Never print private absolute paths or sensitive market rows on failure.
        print('MINUTE_DAY_RAW_PAIR_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
