#!/usr/bin/env python3
"""Read-only, versioned, provenance-limited crosscheck of a declared symbol-day reference.

One side is a SHA-checked TDX DAY live-overlay physical Parquet. The other is
an explicitly supplied SHA-pinned local JSON snapshot of claimed symbol trading
states. Labels and SHA equality do NOT authenticate provider independence,
exchange membership, complete market universe, or eligibility to commit data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, date
from hashlib import sha256
import json
from pathlib import Path

import market_live_day_overlay_audit as OVERLAY
import market_official_day_content_readonly as DAY
import market_quality_source_proofs as PROOF

FORMAT = 'astock_declared_day_symbol_universe_v1'
STATUS = 'DECLARED_DAY_SYMBOL_UNIVERSE_CROSSCHECK_READONLY_NOT_CERTIFIED'
MAX_REFERENCE_BYTES = 4 * 1024 * 1024
MAX_REFERENCE_SYMBOLS = 15000
STATES = frozenset(('TRADED', 'NO_TRADE', 'UNKNOWN'))


class CrosscheckError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise CrosscheckError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(value):
    return sha256(canonical(value)).hexdigest()


def parse_reference(root, relative, expected_sha256, trading_day):
    """Refuse unbounded, duplicate-key or self-asserted uncertified provenance."""
    need(type(expected_sha256) is str and bool(PROOF.HEX64.fullmatch(expected_sha256)),
         'EXPECTED_REFERENCE_SHA_INVALID')
    root = Path(root)
    need(root.is_dir() and not root.is_symlink(), 'REFERENCE_ROOT_INVALID')
    path = PROOF._secure_relative(root, relative)
    actual_sha, size = PROOF._hash_stable_file(path)
    need(0 < size <= MAX_REFERENCE_BYTES, 'REFERENCE_FILE_SIZE_INVALID')
    need(actual_sha == expected_sha256.lower(), 'DECLARED_REFERENCE_BYTES_SHA_MISMATCH')
    doc, parsed_sha = OVERLAY.read_bounded(root, relative, MAX_REFERENCE_BYTES)
    need(parsed_sha == actual_sha, 'REFERENCE_BYTES_CHANGED_DURING_READ')
    need(set(doc) == {'format', 'trading_day', 'source_id', 'coverage_claim', 'symbols'}
         and doc['format'] == FORMAT, 'REFERENCE_FORMAT_INVALID')
    try:
        need(date.fromisoformat(trading_day).isoformat() == trading_day,
             'REQUESTED_DATE_INVALID')
    except (TypeError, ValueError) as exc:
        raise CrosscheckError('REQUESTED_DATE_INVALID') from exc
    need(doc['trading_day'] == trading_day, 'REFERENCE_DATE_DISAGREES_WITH_DAY')
    need(type(doc['source_id']) is str and bool(PROOF.SOURCE.fullmatch(doc['source_id'])),
         'REFERENCE_SOURCE_LABEL_INVALID')
    need(doc['coverage_claim'] in ('FULL_DECLARED', 'PARTIAL_DECLARED'),
         'REFERENCE_COVERAGE_DECLARATION_INVALID')
    items = doc['symbols']
    need(type(items) is list and 0 < len(items) <= MAX_REFERENCE_SYMBOLS,
         'REFERENCE_SYMBOL_COUNT_INVALID')
    result = {}
    for item in items:
        need(type(item) is dict and set(item) == {'symbol', 'trading_state'},
             'REFERENCE_SYMBOL_RECORD_INVALID')
        sym, state = item['symbol'], item['trading_state']
        need(type(sym) is str and bool(PROOF.SYMBOL.fullmatch(sym)),
             'REFERENCE_SYMBOL_CODE_INVALID')
        need(type(state) is str and state in STATES,
             'REFERENCE_TRADING_STATE_INVALID')
        need(sym not in result, 'REFERENCE_DUPLICATE_SYMBOL')
        result[sym] = state
    need(len(result) == len(items), 'REFERENCE_DUPLICATE_SYMBOL')
    return result, {'bytes_sha256': actual_sha,
                    'declared_source_id': doc['source_id'],
                    'declared_coverage': doc['coverage_claim'],
                    'reported_symbols': len(items),
                    'reference_provider_identity_authenticated': False,
                    'reference_full_market_universe_certified': False}


def snapshot_day(rows, trading_day):
    """Pure one-day OHLCVA and code-shape inventory, NOT actual equity universe."""
    try:
        expected = datetime.strptime(trading_day, '%Y-%m-%d').date()
    except (TypeError, ValueError) as exc:
        raise CrosscheckError('INVALID_DAY_DATE') from exc
    need(expected.isoformat() == trading_day, 'INVALID_DAY_DATE')
    found = {}
    nonstandard = total = 0
    for rec in rows:
        total += 1
        need(total <= DAY.MAX_ROWS, 'DAY_ROW_LIMIT_EXCEEDED')
        need(type(rec) is dict and set(DAY.COLS).issubset(rec),
             'DAY_ROW_FIELDS_MISSING')
        raw_ts = rec['ts']
        need(type(raw_ts) is int and 0 < raw_ts < 4102444800000,
             'DAY_ROW_TIMESTAMP_INVALID')
        try:
            day = datetime.fromtimestamp(raw_ts / 1000, tz=DAY.CN).date()
        except (OSError, ValueError, OverflowError) as exc:
            raise CrosscheckError('DAY_ROW_TIMESTAMP_INVALID') from exc
        need(day == expected, 'DAY_ROW_WRONG_DATE')
        # Validate every row's OHLCVA before ignoring any unrecognized symbol.
        vals = {k: DAY.finite_number(rec[k], k, positive=k in DAY.FIELDS[:4])
                for k in DAY.FIELDS}
        need(vals['low'] <= min(vals['open'], vals['close']) <=
             max(vals['open'], vals['close']) <= vals['high'] and
             vals['low'] <= vals['high'], 'DAY_ROW_OHLC_ENVELOPE_INVALID')
        need((vals['volume'] > 0) == (vals['amount'] > 0),
             'DAY_ROW_VOLUME_AMOUNT_INCONSISTENT')
        sym = DAY.normal_symbol(rec['symbol'])
        if sym is None:
            nonstandard += 1
            continue
        need(sym not in found, 'DAY_DUPLICATE_NORMALIZED_CODE')
        found[sym] = vals['volume'] > 0
    need(total > 0, 'DAY_EMPTY')
    return found, {'rows_checked': total, 'normalized_exchange_code_count': len(found),
                   'unrecognized_code_rows': nonstandard,
                   'equity_membership_from_code_shape_certified': False}


def reconcile(day_snapshot, declared):
    """Compare *assertions* only; missing TDX ≠ exchange-defined missing trade."""
    missing_traded = []
    declared_nontraded_active = []
    traded_but_zero = []
    matched_traded = []
    declared_unknown_present = []
    declared_unknown_absent = []
    declared_nontraded_absent = []
    for symbol, state in sorted(declared.items()):
        active = day_snapshot.get(symbol)
        if state == 'TRADED':
            if active is None:
                missing_traded.append(symbol)
            elif active is False:
                traded_but_zero.append(symbol)
            else:
                matched_traded.append(symbol)
        elif state == 'NO_TRADE':
            if active is True:
                declared_nontraded_active.append(symbol)
            elif active is None:
                declared_nontraded_absent.append(symbol)
        elif active is not None:
            declared_unknown_present.append(symbol)
        else:
            declared_unknown_absent.append(symbol)
    only_overlay = sorted(set(day_snapshot) - set(declared))
    groups = {
        'declared_traded_missing_in_overlay': missing_traded,
        'declared_traded_zero_in_overlay': traded_but_zero,
        'declared_no_trade_but_active_in_overlay': declared_nontraded_active,
        'overlay_code_not_in_declared_reference': only_overlay,
        'declared_traded_and_overlay_active': matched_traded,
        'declared_unknown_present_in_overlay': declared_unknown_present,
        'declared_unknown_absent_from_overlay': declared_unknown_absent,
        'declared_no_trade_absent_from_overlay': declared_nontraded_absent,
    }
    # The lists are based on local declarations; they are not an exchange
    # certified active-stock list, even if 'coverage_claim' says FULL.
    return {'groups': groups,
            'counts': {k: len(v) for k, v in groups.items()},
            'has_declared_conflict': any(groups[k] for k in (
                'declared_traded_missing_in_overlay',
                'declared_traded_zero_in_overlay',
                'declared_no_trade_but_active_in_overlay')),
            'declared_comparison_not_official_market_validation': True}


def inspect(module_root, day_label, anchor_symbol, *, reference_root,
            reference_relative, reference_sha256, row_reader=None,
            overlay_checker=None):
    """Verify the genuine accepted TDX DAY chain, then compare a pinned list."""
    root = Path(module_root)
    check = overlay_checker or OVERLAY.inspect
    overlay = check(root, day_label, anchor_symbol, day_reader=row_reader)
    need(overlay.get('status') == OVERLAY.STATUS and
         overlay.get('market_files_written') is False and
         overlay.get('qmt_history_download_calls') == 0 and
         overlay.get('provider_identity_authenticated') is False and
         overlay.get('market_data_write_authorized') is False,
         'OVERLAY_PROOF_AUTHORITY_OR_IDENTITY_CHANGED')
    declared, refmeta = parse_reference(reference_root, reference_relative,
                                        reference_sha256, day_label)
    # Default uses real ParquetFile; dependency injection only for synthetic
    # contract tests. Both run same pure OHLCVA grid/normalized code rules.
    work = root / 'work'
    rel = f'incremental/day/year={day_label[:4]}/{day_label}.parquet'
    source = PROOF._secure_relative(work, rel)
    before_sha, before_size = PROOF._hash_stable_file(source)
    need(before_sha == overlay['day_overlay_parquet_bytes_sha256'],
         'OVERLAY_FILE_SHA_CHANGED_BEFORE_COMPARISON')
    reader = row_reader or DAY._parquet_rows
    inventory, stats = snapshot_day(reader(source), day_label)
    after_sha, after_size = PROOF._hash_stable_file(source)
    need(after_sha == before_sha and after_size == before_size,
         'OVERLAY_FILE_CHANGED_DURING_COMPARISON')
    need(stats['rows_checked'] == overlay['day_overlay_rows_verified'],
         'OVERLAY_ROW_COUNT_CHANGED_DURING_COMPARISON')
    # Pin metadata again after second complete Parquet scan.
    state, stsha = OVERLAY.read_bounded(work, 'state.json', OVERLAY.MAX_STATE_BYTES)
    receipt_rel = rel.removesuffix('.parquet') + '.json'
    receipt, rsha = OVERLAY.read_bounded(work, receipt_rel, OVERLAY.MAX_RECEIPT_BYTES)
    need(stsha == overlay['live_state_bytes_sha256'] and
         rsha == overlay['day_overlay_receipt_bytes_sha256'],
         'OVERLAY_STATE_OR_RECEIPT_CHANGED_DURING_COMPARISON')
    _, final_refmeta = parse_reference(reference_root, reference_relative,
                                       reference_sha256, day_label)
    need(final_refmeta == refmeta, 'REFERENCE_CHANGED_DURING_COMPARISON')
    comparison = reconcile(inventory, declared)
    report = {
        'status': STATUS, 'day': day_label,
        'anchor_symbol': anchor_symbol,
        'tdx_overlay_parquet_bytes_sha256': before_sha,
        'tdx_overlay_state_bytes_sha256': stsha,
        'tdx_overlay_receipt_bytes_sha256': rsha,
        'reference_bytes_sha256': refmeta['bytes_sha256'],
        'declared_reference_source_id': refmeta['declared_source_id'],
        'declared_reference_coverage_claim': refmeta['declared_coverage'],
        'reference_symbol_count': refmeta['reported_symbols'],
        **stats, **comparison,
        'independent_reference_provider_authenticated': False,
        'reference_full_stock_day_universe_certified': False,
        'tdx_provider_identity_authenticated': False,
        'instrument_membership_authenticated': False,
        'source_independence_authenticated': False,
        'native_qmt_1min_certified': False,
        'original_producer_quarantines_cleared': False,
        'market_quality_cleared': False,
        'market_write_authorized': False,
        'market_files_written': False,
        'qmt_history_download_calls': 0,
    }
    report['comparison_json_sha256'] = sha(report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    p.add_argument('--trading-day', required=True)
    p.add_argument('--anchor-symbol', required=True)
    p.add_argument('--reference-root', type=Path, required=True)
    p.add_argument('--reference-relative', required=True)
    p.add_argument('--reference-sha256', required=True)
    p.add_argument('--summary-only', action='store_true')
    a = p.parse_args(argv)
    try:
        r = inspect(a.module_root, a.trading_day, a.anchor_symbol,
                    reference_root=a.reference_root,
                    reference_relative=a.reference_relative,
                    reference_sha256=a.reference_sha256)
        out = ({k: v for k, v in r.items() if k != 'groups'}
               if a.summary_only else r)
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False))
        return 0
    except (CrosscheckError, OVERLAY.OverlayError, DAY.DayContentError,
            PROOF.ProofError, OSError, ValueError, TypeError, KeyError,
            ImportError, RuntimeError) as exc:
        # Only error types, not private file contents/paths.
        print('DAY_REFERENCE_CROSSCHECK_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
