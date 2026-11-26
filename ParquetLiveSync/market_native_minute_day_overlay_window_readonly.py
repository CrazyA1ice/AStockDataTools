#!/usr/bin/env python3
"""Read-only cross-day raw QMT-probe vs pinned local TDX DAY-overlay diagnostics.

This does not certify either provider, paid calibration, six-field market
quality, missing stock-day coverage or transaction/production write authority.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
from hashlib import sha256
import json
import math
from pathlib import Path

import market_native_minute_window_readonly as WINDOW
import market_native_minute_jsonl_readonly as MINUTE
import market_live_day_overlay_audit as OVERLAY
import market_minute_day_raw_pair_readonly as PAIR
import market_quality_source_proofs as PROOF
import market_official_day_content_readonly as DAY

FORMAT = 'astock_native_minute_live_day_overlay_raw_diagnostics_v1'
STATUS = 'LOCAL_MINUTE_VS_PINNED_DAY_OVERLAY_RAW_DELTAS_NOT_CALIBRATED'
MAX_DAY_COMPARISONS = 32
SOFT_MISSING = {
    'DAY_NOT_FOUND_IN_PINNED_LIVE_STATE': 'DECLARED_DAY_OVERLAY_NOT_REGISTERED',
    'DAY_NOT_IN_OVERLAY_WINDOW': 'DAY_OUTSIDE_DECLARED_OVERLAY_BASE_WINDOW',
    'TARGET_EQUITY_NOT_IN_DAY_EXPORT': 'TARGET_MISSING_IN_DECLARED_DAY',
    'TARGET_DAY_NOT_ACTIVE_TRADED_REFERENCE': 'TARGET_NOT_ACTIVE_IN_DECLARED_DAY',
}


class OverlayPairError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise OverlayPairError(reason)


def _identity(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _check_overlay(evidence, symbol, day):
    """Explicitly reject any made-up or upgraded DAY/market authority flags."""
    need(type(evidence) is dict and evidence.get('status') == OVERLAY.STATUS and
         evidence.get('day') == day and evidence.get('symbol') == symbol and
         evidence.get('day_content_fields_and_target_checked') is True and
         evidence.get('whole_exchange_stock_day_universe_certified') is False and
         evidence.get('provider_identity_authenticated') is False and
         evidence.get('tdx_raw_zip_bytes_verified') is False and
         evidence.get('tdx_raw_zip_file_bytes_sha256_if_checked') is None and
         evidence.get('qmt_native_1min_verified') is False and
         evidence.get('market_candidate_validated') is False and
         evidence.get('original_nine_quarantines_cleared') is False and
         evidence.get('market_data_write_authorized') is False and
         evidence.get('market_files_written') is False and
         type(evidence.get('qmt_history_download_calls')) is int and
         evidence['qmt_history_download_calls'] == 0 and
         all(type(evidence.get(key)) is str and
             bool(PROOF.HEX64.fullmatch(evidence[key])) for key in
             ('live_state_bytes_sha256', 'day_overlay_receipt_bytes_sha256',
              'day_overlay_parquet_bytes_sha256')),
         'OVERLAY_REPORT_SCOPE_OR_AUTHORITY_INVALID')
    return PAIR._strict_ohlcva(evidence.get('target_ohlcva'), 'DAY')


def inspect(minute_root, minute_relative, minute_sha256, symbol, start_day,
            end_day, module_root, *, overlay_reader=None):
    """Fully validate minute window, then compare only actual 241-grid dates."""
    minutes = WINDOW.inspect(minute_root, minute_relative, minute_sha256,
                             symbol, start_day, end_day)
    normalized = MINUTE.normalize_symbol(symbol)
    need(minutes.get('status') == WINDOW.STATUS and
         minutes.get('declared_symbol') == normalized and
         minutes.get('physical_local_file_sha256') == minute_sha256.lower() and
         minutes.get('source_file_bytes_verified') is True and
         minutes.get('native_qmt_provider_origin_authenticated') is False and
         minutes.get('production_merge_authorized') is False and
         minutes.get('market_files_written') is False and
         type(minutes.get('qmt_history_download_calls')) is int and
         minutes['qmt_history_download_calls'] == 0,
         'MINUTE_WINDOW_REPORT_SCOPE_OR_AUTHORITY_INVALID')
    day_symbol = normalized[-2:] + normalized[:6]
    days = minutes['days']
    ready = [d for d in days if d['grid_status'] == 'EXACT_241_WITH_0930']
    need(len(ready) <= MAX_DAY_COMPARISONS, 'OVERLAY_PAIR_DAY_COMPARISON_BUDGET')
    root = Path(module_root)
    need(root.is_dir() and not root.is_symlink(), 'DAY_OVERLAY_MODULE_ROOT_INVALID')
    minute_root = Path(minute_root)
    path = PROOF._secure_relative(minute_root, minute_relative)
    initial_id = _identity(path)
    need(initial_id[2] == minutes['physical_local_file_bytes'],
         'MINUTE_SOURCE_SIZE_CHANGED_BEFORE_PAIR')
    grouped = defaultdict(list)
    total = 0
    for row in MINUTE._file_rows(path):
        total += 1
        need(total <= MINUTE.MAX_ROWS, 'OVERLAY_PAIR_MINUTE_ROW_BUDGET')
        # The first WINDOW pass already checked every row's content. The
        # second pass must conserve every date's original count exactly.
        day_key = row['datetime_cn'][:10]
        grouped[day_key].append(row)
    need(total == minutes['rows_structurally_and_numerically_validated'] and
         {d['day']: d['rows'] for d in days if d['rows']} ==
         {key: len(rows) for key, rows in grouped.items()},
         'MINUTE_SOURCE_ROWS_CHANGED_BETWEEN_PASSES')
    lookup = overlay_reader if overlay_reader is not None else OVERLAY.inspect
    compared = []
    counts = Counter()
    source_state_sha = None
    for d in days:
        entry = {
            'day': d['day'], 'minute_rows': d['rows'],
            'minute_grid_status': d['grid_status'],
            'declared_day_overlay_state': None,
            'raw_six_field_difference_without_calibration': None,
            'provider_identity_authenticated': False,
            'six_field_quality_certified': False,
            'production_repair_authorized': False,
        }
        if d['grid_status'] != 'EXACT_241_WITH_0930':
            entry['declared_day_overlay_state'] = (
                'NO_MINUTE_ROWS_CALENDAR_DAY_NOT_TRADING_CERTIFIED'
                if d['rows'] == 0 else 'MINUTE_GRID_INCOMPLETE_NOT_COMPARED')
        else:
            minute_result = MINUTE.check_rows(
                grouped[d['day']], target_symbol=normalized,
                target_day=d['day'], start_day=d['day'], end_day=d['day'])
            raw = PAIR._strict_ohlcva(
                minute_result['raw_uncalibrated_target_ohlcva'], 'MINUTE')
            try:
                overlay = lookup(root, d['day'], day_symbol)
            except (OVERLAY.OverlayError, DAY.DayContentError) as exc:
                status = SOFT_MISSING.get(str(exc))
                if status is None:
                    raise
                entry['declared_day_overlay_state'] = status
            else:
                daily = _check_overlay(overlay, day_symbol, d['day'])
                current_state = overlay['live_state_bytes_sha256'].lower()
                if source_state_sha is None:
                    source_state_sha = current_state
                need(current_state == source_state_sha,
                     'DAY_OVERLAY_STATE_CHANGED_BETWEEN_DATES')
                diff = {}
                for field in PAIR.FIELDS:
                    signed = raw[field] - daily[field]
                    relative = signed / max(abs(daily[field]), 1e-12)
                    need(math.isfinite(signed) and math.isfinite(relative),
                         'DAY_PAIR_RAW_DIFFERENCE_OVERFLOW')
                    diff[field] = {
                        'minute_raw': raw[field], 'declared_day': daily[field],
                        'raw_delta': signed, 'raw_relative_delta': relative,
                    }
                entry['declared_day_overlay_state'] = 'LOCAL_DAY_OVERLAY_CONTENT_SHA_VERIFIED_RAW_DIAGNOSTICS'
                entry['day_overlay_parquet_bytes_sha256'] = overlay['day_overlay_parquet_bytes_sha256']
                entry['day_overlay_receipt_bytes_sha256'] = overlay['day_overlay_receipt_bytes_sha256']
                entry['raw_six_field_difference_without_calibration'] = diff
        counts[entry['declared_day_overlay_state']] += 1
        compared.append(entry)
    final_sha, final_size = PROOF._hash_stable_file(path)
    need(final_sha == minute_sha256.lower() and
         final_size == minutes['physical_local_file_bytes'] and
         initial_id == _identity(path) and
         path == PROOF._secure_relative(minute_root, minute_relative),
         'MINUTE_SOURCE_CHANGED_DURING_OVERLAY_PAIR')
    pair_identity = {
        'symbol': normalized, 'window': minutes['declared_window'],
        'minute_file_sha256': final_sha, 'day_overlay_state_sha256': source_state_sha,
        'day_digests': [(x['day'], x.get('day_overlay_parquet_bytes_sha256'))
                        for x in compared],
    }
    pair_sha = sha256(PROOF.canonical(pair_identity)).hexdigest()
    return {
        'format': FORMAT, 'status': STATUS, 'symbol': normalized,
        'window': minutes['declared_window'],
        'minute_physical_file_sha256': final_sha,
        'local_day_overlay_state_sha256_if_observed': source_state_sha,
        'raw_diagnostic_scope_sha256': pair_sha,
        'calendar_days': len(days), 'minute_rows_checked': total,
        'day_overlay_status_counts': dict(sorted(counts.items())),
        'days': compared,
        'data_source_independence_or_provider_identity_certified': False,
        'official_exchange_calendar_and_stock_universe_certified': False,
        'qmt_native_provider_authenticated': False,
        'paid_minutes_units_or_timestamp_calibrated': False,
        'six_field_quality_passed': False,
        'eight_period_aggregation_reconciled': False,
        'market_candidate_validated': False,
        'producer_quarantine_closed': False,
        'backup_materialized': False,
        'physical_source_lock_held': False,
        'production_merge_authorized': False,
        'market_files_written': False,
        'qmt_cache_modified': False,
        'qmt_history_download_calls': 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minute-evidence-root', required=True, type=Path)
    parser.add_argument('--minute-file-relative', required=True)
    parser.add_argument('--expected-minute-sha256', required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--start-day', required=True)
    parser.add_argument('--end-day', required=True)
    parser.add_argument('--module-root', required=True, type=Path)
    a = parser.parse_args(argv)
    try:
        result = inspect(a.minute_evidence_root, a.minute_file_relative,
                         a.expected_minute_sha256, a.symbol,
                         a.start_day, a.end_day, a.module_root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False))
        return 0
    except (OverlayPairError, MINUTE.NativeMinuteError, WINDOW.WindowError,
            OVERLAY.OverlayError, DAY.DayContentError, PROOF.ProofError,
            ValueError, OSError, TypeError, KeyError, OverflowError,
            ImportError, RuntimeError) as exc:
        print('MINUTE_DAY_OVERLAY_PAIR_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
