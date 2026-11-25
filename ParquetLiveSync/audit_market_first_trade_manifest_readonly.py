#!/usr/bin/env python3
"""Non-admitting, deterministic manifest of two 2026-11-25 opening candidates.

The report is obtained from the existing SHA-bound, read-only QMT replay.
Never downloads history, alters raw 241 bars, writes a report, or admits a
candidate to purchased 240-minute/production stock-day data. Its digest binds
to *diagnostic JSON*, NOT the original 241-bar source bytes or a signed feed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from audit_market_opening_auction_readonly import run_audit

RUN_SHA = '72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837'
OFFICIAL_SHA = '5519a56731a6bdb09b973fcc9ff7cd5b636f325880a94bbf9ee886a505d305e6'
OFFICIAL_RECEIPT_SHA = '5bb4616e7d97cf547cded994fefd05fbacc568a2f573a8ff63e5970564496e2d'
ORIGINAL_FAILURE = 'ValueError: Independent official DAY materialized OHLC discrepancy: open'
EXPECTED = {
    'SH605336': ('09:32', 7.62, 7.69, 2),
    'SZ300462': ('09:33', 9.40, 9.59, 3),
}
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')


class ManifestError(ValueError):
    pass


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def _check(condition, reason):
    if not condition:
        raise ManifestError(reason)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError('INVALID_NUMERIC_FIELD')
    val = float(value)
    if not math.isfinite(val):
        raise ManifestError('NONFINITE_NUMERIC_FIELD')
    return val


def certify_diagnostic_only(report):
    """Validate replay consistency and emit NO-WRITE review-only evidence.

    The caller must already run the exact original scheduled-run/official-DAY
    source and paid-calibration pins enforced by run_audit(). No QMT source
    SHA is invented here; source JSON digest is only a reproducible snapshot.
    """
    _check(isinstance(report, dict), 'REPORT_NOT_OBJECT')
    _check(report.get('status') == 'TWO_STOCK_OPENING_PROVENANCE_READ_ONLY_NOT_REPAIR',
           'WRONG_AUDIT_STATUS')
    _check(report.get('original_run_sha256') == RUN_SHA, 'ORIGINAL_RUN_SHA_CHANGED')
    _check(report.get('official_day_overlay_parquet_sha256') == OFFICIAL_SHA,
           'OFFICIAL_DAY_SOURCE_CHANGED')
    _check(report.get('official_day_overlay_receipt_sha256') == OFFICIAL_RECEIPT_SHA,
           'OFFICIAL_DAY_RECEIPT_CHANGED')
    for key in ('project_data_modified', 'qmt_historical_download_called',
                'data_quality_cleared'):
        _check(report.get(key) is False, 'REPORTED_SIDE_EFFECT_OR_QUALITY_CHANGED_' + key)
    rows = report.get('stocks')
    _check(isinstance(rows, list) and len(rows) == 2, 'EXPECTED_EXACT_TWO_STOCKS')
    _check({r.get('symbol') for r in rows if isinstance(r, dict)} == set(EXPECTED),
           'CANDIDATE_SYMBOLS_CHANGED_OR_DUPLICATED')
    candidates = []
    for row in sorted(rows, key=lambda x: x['symbol']):
        symbol = row['symbol']
        label, expected_open, quote_open, expected_zero = EXPECTED[symbol]
        first = row.get('first_positive_trade_diagnostic')
        _check(isinstance(first, dict), 'FIRST_TRADE_DIAGNOSTIC_MISSING_' + symbol)
        _check(row.get('date') == '2026-11-25' and row.get('native_labels') == 241
               and row.get('folded_labels') == 240, 'ORIGINAL_NATIVE_GRID_CHANGED_' + symbol)
        _check(row.get('auction_kind') == 'ZERO_PLACEHOLDER',
               'REAL_0930_AUCTION_CANNOT_USE_ZERO_PREFIX_POLICY_' + symbol)
        _check(_number(row.get('raw_0930_volume')) == 0 and
               _number(row.get('raw_0930_amount')) == 0,
               '0930_NOT_ZERO_PLACEHOLDER_' + symbol)
        _check(row.get('all_data_changes_committed') is False,
               'SOURCE_ALREADY_MODIFIED_' + symbol)
        _check(row.get('folded_ohlc_validation_error') == ORIGINAL_FAILURE and
               row.get('full_original_validation_error') == ORIGINAL_FAILURE,
               'ORIGINAL_QUARANTINE_NO_LONGER_REPRODUCES_' + symbol)
        _check(first.get('status') == 'FIRST_TRADE_OPEN_COMPATIBLE_CANDIDATE_ONLY'
               and first.get('admission_authorized') is False
               and first.get('strict_official_open_match') is True
               and first.get('traded_hlc_match') is True
               and first.get('post_prefix_hlc_match') is True,
               'FIRST_TRADE_NOT_STRICTLY_COMPATIBLE_' + symbol)
        _check(first.get('first_positive_label') == label
               and first.get('zero_prefix_bars') == expected_zero,
               'FIRST_TRADE_CLOCK_CHANGED_' + symbol)
        _check(_number(first.get('first_positive_open')) == expected_open
               and _number(row.get('official_day_open')) == expected_open,
               'FIRST_TRADE_OFFICIAL_OPEN_CHANGED_' + symbol)
        _check(all(_number(row.get(k)) == quote_open for k in
                   ('raw_0931_open', 'folded_0931_open')),
               'QMT_PRETRADE_QUOTE_CHANGED_' + symbol)
        official, folded = row.get('official_day_ohlcva'), row.get('folded_day_ohlcva')
        comparison = row.get('field_comparisons')
        _check(isinstance(official, dict) and isinstance(folded, dict)
               and isinstance(comparison, dict) and set(comparison) == set(FIELDS),
               'SIX_FIELD_COMPARISON_MISSING_' + symbol)
        _check(_number(official['open']) == expected_open and
               _number(folded['open']) == quote_open,
               'DAILY_OPEN_EVIDENCE_CHANGED_' + symbol)
        for key in FIELDS:
            actual, reference = _number(folded[key]), _number(official[key])
            rel = .03 if key in ('volume', 'amount') else .006
            abs_tol = 200 if key == 'volume' else 1000 if key == 'amount' else .04
            within = math.isclose(actual, reference, rel_tol=rel, abs_tol=abs_tol)
            entry = comparison[key]
            _check(isinstance(entry, dict)
                   and entry.get('within_existing_tolerance') is within
                   and math.isclose(_number(entry.get('absolute_difference')),
                                    actual-reference, rel_tol=0, abs_tol=1e-7),
                   'REPORTED_COMPARISON_INCONSISTENT_' + symbol + '_' + key)
            _check(within == (key != 'open'), 'UNEXPECTED_EXTRA_FIELD_MISMATCH_'+symbol+'_'+key)
        _check(row.get('outside_official_high_low_envelope') is False,
               'OFFICIAL_DAY_ENVELOPE_VIOLATED_' + symbol)
        _check(not (float(folded['high']) > float(official['high'])+.005
                    or float(folded['low']) < float(official['low'])-.005),
               'RECOMPUTED_DAY_ENVELOPE_VIOLATED_' + symbol)
        candidates.append({
            'symbol': symbol,
            'first_genuine_trade_label': label,
            'first_genuine_trade_open': expected_open,
            'official_day_open': expected_open,
            'pretrade_0931_reference_open': quote_open,
            'original_native_241_labels': 241,
            'zero_volume_amount_prefix': expected_zero,
            'traded_and_tail_hlc_within_original_tolerance': True,
            'original_240_market_validation_still_rejects_open': True,
            'admission_authorized': False,
        })
    manifest = {
        'status': 'FIRST_TRADE_OPENING_CANDIDATES_VERIFIED_DIAGNOSTIC_ONLY',
        'date': '2026-11-25',
        'source': {'scheduled_run_sha256': RUN_SHA,
                   'official_day_overlay_sha256': OFFICIAL_SHA,
                   'official_day_receipt_sha256': OFFICIAL_RECEIPT_SHA},
        'diagnostic_snapshot_sha256': digest(report),
        'diagnostic_digest_scope': 'REPLAY_JSON_ONLY_NOT_RAW_241_OR_PROVIDER_SIGNATURE',
        'candidate_count': 2,
        'candidates': candidates,
        'original_nine_quarantines_retained': True,
        'project_market_files_modified': False,
        'qmt_history_download_called': False,
        'production_merge_authorized': False,
        'data_quality_cleared': False,
    }
    manifest['manifest_sha256'] = digest(manifest)
    return manifest


def main(argv=None, *, runner=run_audit):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--confirm-two-stock-cache-query', action='store_true')
    args = parser.parse_args(argv)
    try:
        _check(args.confirm_two_stock_cache_query, 'QMT_CACHE_QUERY_NOT_EXPLICITLY_ENABLED')
        report = runner(args.module_root, confirm=True)
        print(json.dumps(certify_diagnostic_only(report), ensure_ascii=False,
                         sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ManifestError, ValueError, KeyError, TypeError, OSError, RuntimeError,
            ImportError) as exc:
        print('FIRST_TRADE_MANIFEST_REVIEW_REQUIRED: ' + type(exc).__name__ +
              ': ' + str(exc)[:160])
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
