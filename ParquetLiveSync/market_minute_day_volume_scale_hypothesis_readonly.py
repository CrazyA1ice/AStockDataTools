#!/usr/bin/env python3
"""Read-only candidate volume-unit ratio study of verified native-minute / DAY pairs.

Candidate factors are *unapproved hypotheses*, not conversions, independently
verified provider units, six-field market quality, or production repair authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics

import market_native_minute_day_overlay_window_readonly as PAIR
import market_minute_day_raw_pair_readonly as RAW
import market_quality_source_proofs as PROOF

FORMAT = 'astock_minute_day_volume_scale_hypothesis_readonly_v1'
STATUS = 'DESCRIPTIVE_CANDIDATE_VOLUME_UNIT_SCALE_NOT_CALIBRATED'
FACTORS = (1, 10, 100, 1000)
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')
PAIRED = 'LOCAL_DAY_OVERLAY_CONTENT_SHA_VERIFIED_RAW_DIAGNOSTICS'
MAX_DAYS = 64


class HypothesisError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise HypothesisError(reason)


def bounded_number(x, name, *, nonnegative=False):
    require(type(x) in (int, float), name + '_NOT_NUMBER')
    try:
        result = float(x)
    except (OverflowError, TypeError, ValueError) as exc:
        raise HypothesisError(name + '_INVALID') from exc
    require(math.isfinite(result) and (result >= 0 if nonnegative else True),
            name + '_NONFINITE_OR_NEGATIVE')
    return result


def dist(values):
    require(len(values) > 0, 'EMPTY_DIAGNOSTIC_SAMPLE')
    x = sorted(values)
    return {
        'count': len(x),
        'median': statistics.median(x),
        'p95_nearest_rank': x[math.ceil(.95 * len(x)) - 1],
        'maximum': x[-1],
    }


def _check_header(record):
    require(type(record) is dict and
            record.get('format') == PAIR.FORMAT and
            record.get('status') == PAIR.STATUS and
            type(record.get('symbol')) is str and
            type(record.get('window')) is list and len(record['window']) == 2 and
            all(type(d) is str for d in record['window']) and
            type(record.get('calendar_days')) is int and
            1 <= record['calendar_days'] <= MAX_DAYS and
            type(record.get('minute_rows_checked')) is int and
            0 < record['minute_rows_checked'] <= 20_000 and
            type(record.get('days')) is list and
            len(record['days']) == record['calendar_days'] and
            type(record.get('day_overlay_status_counts')) is dict and
            all(type(record.get(key)) is str and
                PROOF.HEX64.fullmatch(record[key]) for key in
                ('minute_physical_file_sha256', 'raw_diagnostic_scope_sha256')),
            'PAIR_HEADER_IDENTITY_INVALID')
    for flag in ('data_source_independence_or_provider_identity_certified',
                 'official_exchange_calendar_and_stock_universe_certified',
                 'qmt_native_provider_authenticated',
                 'paid_minutes_units_or_timestamp_calibrated',
                 'six_field_quality_passed','eight_period_aggregation_reconciled',
                 'market_candidate_validated','producer_quarantine_closed',
                 'backup_materialized','physical_source_lock_held',
                 'production_merge_authorized','market_files_written',
                 'qmt_cache_modified'):
        require(record.get(flag) is False, 'PAIR_UNAUTHORIZED_MARKER_' + flag)
    require(type(record.get('qmt_history_download_calls')) is int and
            record['qmt_history_download_calls'] == 0,
            'PAIR_HISTORY_DOWNLOAD_CLAIM_INVALID')


def _source_values(day, field):
    row = day['raw_six_field_difference_without_calibration'][field]
    require(type(row) is dict and
            set(row) == {'minute_raw', 'declared_day','raw_delta',
                         'raw_relative_delta'}, 'PAIR_FIELD_SCHEMA_INVALID')
    m = bounded_number(row['minute_raw'], 'MINUTE_'+field, nonnegative=True)
    d = bounded_number(row['declared_day'], 'DAY_'+field, nonnegative=True)
    delta = bounded_number(row['raw_delta'], 'DELTA_'+field)
    rel = bounded_number(row['raw_relative_delta'], 'RELATIVE_'+field)
    require(m >= 0 and d >= 0 and
            (m > 0 and d > 0 if field in FIELDS[:4] else True),
            'PAIR_INVALID_OHLC_OR_VOLUME')
    require(math.isclose(m-d, delta, rel_tol=1e-12, abs_tol=1e-8) and
            math.isclose(delta / max(abs(d),1e-12), rel,
                         rel_tol=1e-12, abs_tol=1e-9),
            'PAIR_FIELD_RAW_DELTA_NOT_CONSERVED')
    return m, d


def summarize(report):
    """Summarize observations, never alter source or recommend applying a factor."""
    _check_header(report)
    errors = {k: [] for k in FIELDS}
    scales = {c: [] for c in FACTORS}
    volume_ratios, compared = [], []
    nonpaired = Counter()
    days_seen = set()
    row_total = 0
    status_counts = Counter()
    previous = None
    for day in report['days']:
        require(type(day) is dict and type(day.get('day')) is str and
                type(day.get('minute_rows')) is int and 0 <= day['minute_rows'] <= 241 and
                type(day.get('declared_day_overlay_state')) is str and
                type(day.get('minute_grid_status')) is str and
                day.get('provider_identity_authenticated') is False and
                day.get('six_field_quality_certified') is False and
                day.get('production_repair_authorized') is False,
                'PAIR_DAY_SCHEMA_OR_AUTHORITY_INVALID')
        key = day['day']
        require(key not in days_seen and
                (previous is None or key > previous) and
                report['window'][0] <= key <= report['window'][1],
                'PAIR_DAY_WINDOW_DUPLICATE_OR_ORDER_INVALID')
        days_seen.add(key); previous=key
        row_total += day['minute_rows']
        state=day['declared_day_overlay_state']
        status_counts[state]+=1
        if state != PAIRED:
            require(day.get('raw_six_field_difference_without_calibration') is None,
                    'UNPAIRED_DAY_HAS_FORGED_NUMERIC_DATA')
            nonpaired[state]+=1
            continue
        require(day['minute_rows'] == 241 and
                day['minute_grid_status'] == 'EXACT_241_WITH_0930' and
                type(day.get('raw_six_field_difference_without_calibration')) is dict and
                set(day['raw_six_field_difference_without_calibration']) == set(FIELDS) and
                all(type(day.get(k)) is str and
                    PROOF.HEX64.fullmatch(day[k]) for k in
                    ('day_overlay_parquet_bytes_sha256',
                     'day_overlay_receipt_bytes_sha256')),
                'PAIRED_241_AND_DAY_PROOF_REQUIRED')
        values = {}
        for field in FIELDS:
            m,d = _source_values(day,field)
            values[field]=(m,d)
            if d > 0:
                errors[field].append(abs(m-d)/d)
        mv,dv=values['volume']
        if dv > 0:
            volume_ratios.append(mv/dv)
            for candidate in FACTORS:
                delta = abs(mv*candidate-dv)/dv
                require(math.isfinite(delta), 'CANDIDATE_ERROR_OVERFLOW')
                scales[candidate].append(delta)
        compared.append(key)
    require(row_total == report['minute_rows_checked'] and
            dict(status_counts) == record_counts(report['day_overlay_status_counts']),
            'SOURCE_PAIR_COUNTS_DISAGREE')
    require(len(compared)>0, 'NO_COMPARABLE_PINNED_DAY_EVIDENCE')
    require(len(volume_ratios)>0,'NO_POSITIVE_VOLUME_REFERENCE_FOR_HYPOTHESIS')
    summary={str(c):dist(scales[c]) for c in FACTORS}
    best=min(FACTORS, key=lambda c:(summary[str(c)]['median'],c))
    per_field={k:dist(v) if v else None for k,v in errors.items()}
    scope={'upstream_raw_diagnostic_sha256':report['raw_diagnostic_scope_sha256'],
           'minute_source_sha256':report['minute_physical_file_sha256'],
           'symbol':report['symbol'],'window':report['window'],
           'observed_days':compared,'candidate_factors':FACTORS}
    return {
        'format':FORMAT,'status':STATUS,
        'symbol':report['symbol'], 'window':report['window'],
        'minute_source_sha256':report['minute_physical_file_sha256'],
        'upstream_raw_diagnostic_scope_sha256':report['raw_diagnostic_scope_sha256'],
        'descriptive_hypothesis_scope_sha256':sha256(PROOF.canonical(scope)).hexdigest(),
        'physical_day_comparisons':len(compared),'paired_dates':compared,
        'minute_rows_checked':row_total,'nonpaired_status_counts':dict(sorted(nonpaired.items())),
        'volume_minute_over_day_ratio':dist(volume_ratios),
        'volume_candidate_abs_relative_error':summary,
        'lowest_median_error_candidate_not_approved':best,
        'six_fields_raw_abs_relative_error':per_field,
        'amount_raw_abs_relative_error':per_field['amount'],
        'price_raw_abs_relative_error':{k:per_field[k] for k in FIELDS[:4]},
        'candidate_factor_is_approved_calibration':False,
        'volume_factor_applied_to_data':False,
        'independent_provider_identity_verified':False,
        'purchased_feed_units_or_timestamp_calibrated':False,
        'six_field_quality_passed':False,
        'producer_quarantine_closed':False,
        'market_candidate_validated':False,
        'production_merge_authorized':False,
        'market_files_written':False,
        'qmt_cache_modified':False,
        'qmt_download_calls':0,
    }


def record_counts(raw):
    require(type(raw) is dict and
            all(type(k) is str and type(v) is int and v >= 0
                for k,v in raw.items()),
            'PAIR_STATUS_COUNTS_INVALID')
    return dict(raw)


def inspect(minute_root,minute_relative,minute_sha256,symbol,
            start_day,end_day,module_root):
    return summarize(PAIR.inspect(minute_root,minute_relative,minute_sha256,
                                  symbol,start_day,end_day,module_root))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--minute-evidence-root',required=True,type=Path)
    p.add_argument('--minute-file-relative',required=True)
    p.add_argument('--expected-minute-sha256',required=True)
    p.add_argument('--symbol',required=True)
    p.add_argument('--start-day',required=True)
    p.add_argument('--end-day',required=True)
    p.add_argument('--module-root',required=True,type=Path)
    a=p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.minute_evidence_root,a.minute_file_relative,
                                 a.expected_minute_sha256,a.symbol,
                                 a.start_day,a.end_day,a.module_root),
                         ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False))
        return 0
    except (HypothesisError,PAIR.OverlayPairError,ValueError,TypeError,
            KeyError,OSError,OverflowError,ImportError,RuntimeError) as exc:
        print('MINUTE_DAY_SCALE_HYPOTHESIS_REVIEW_REQUIRED: '+type(exc).__name__)
        return 3


if __name__=='__main__':
    raise SystemExit(main())
