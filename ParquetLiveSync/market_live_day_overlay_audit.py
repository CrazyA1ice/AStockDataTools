#!/usr/bin/env python3
"""Read-only, date-neutral audit of one accepted TDX DAY overlay + receipt.

Never interprets an accepted DAY as proof of an absent QMT minute bar.
State/receipt hashes and local Parquet content are checked, NOT the underlying
vendor ZIP source bytes or authenticity of the TDX provider assertion.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re

import market_official_day_content_readonly as DAY
import market_quality_source_proofs as PROOF

FORMAT = 'a_stock_data_tdx_day_live_parquet_overlay_v1'
BASE_SHA = 'a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01'
BASE_DAY = date(2026, 10, 13)
STATUS = 'PINNED_TDX_DAY_OVERLAY_RECEIPT_AND_CONTENT_READONLY'
MAX_STATE_BYTES = 10_000_000
MAX_RECEIPT_BYTES = 1_000_000


class OverlayError(ValueError):
    pass


def demand(condition, message):
    if not condition:
        raise OverlayError(message)


def pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        demand(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def read_bounded(root, relative, limit):
    path = PROOF._secure_relative(root, relative)
    demand(0 < path.stat().st_size <= limit, 'SOURCE_METADATA_SIZE_INVALID')
    first_sha, first_size = PROOF._hash_stable_file(path)
    raw = path.read_bytes()
    last_sha, last_size = PROOF._hash_stable_file(path)
    demand(first_sha == last_sha == sha256(raw).hexdigest()
           and first_size == last_size == len(raw),
           'SOURCE_METADATA_CHANGED_DURING_READ')
    try:
        decoded = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs_no_duplicates)
    except OverlayError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise OverlayError('SOURCE_METADATA_INVALID_JSON') from exc
    demand(isinstance(decoded, dict), 'SOURCE_METADATA_NOT_OBJECT')
    return decoded, first_sha


def inspect(module_root, day_label, symbol, *, raw_zip_relative=None, day_reader=None):
    """Bind state, daily receipt and full selected-day Parquet physical bytes.

    Caller must supply the *real* ParquetLiveSync module directory, not a
    detached source-only worktree. No scans, downloads or persistent writes.
    """
    root = Path(module_root)
    demand(root.is_dir() and not root.is_symlink(), 'MODULE_ROOT_INVALID')
    work = root / 'work'
    demand(work.is_dir() and not work.is_symlink(), 'OVERLAY_WORK_DIR_INVALID')
    demand(type(day_label) is str and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', day_label)),
           'INVALID_REQUESTED_DATE')
    try:
        day = date.fromisoformat(day_label)
    except ValueError as exc:
        raise OverlayError('INVALID_REQUESTED_DATE') from exc
    demand(day.isoformat() == day_label and day > BASE_DAY, 'DAY_NOT_IN_OVERLAY_WINDOW')
    demand(type(symbol) is str and bool(PROOF.SYMBOL.fullmatch(symbol)),
           'INVALID_TARGET_SYMBOL')

    state, state_hash = read_bounded(work, 'state.json', MAX_STATE_BYTES)
    demand(state.get('format') == FORMAT and
           state.get('base_dataset_sha256') == BASE_SHA and
           state.get('base_day') == BASE_DAY.isoformat() and
           state.get('production_activated') is False and
           type(state.get('days')) is dict, 'OVERLAY_STATE_IDENTITY_INVALID')
    entry = state['days'].get(day_label)
    demand(type(entry) is dict, 'DAY_NOT_FOUND_IN_PINNED_LIVE_STATE')
    rel = f'incremental/day/year={day.year}/{day_label}.parquet'
    demand(entry.get('file') == rel and type(entry.get('rows')) is int and
           1 <= entry['rows'] <= 15000 and
           isinstance(entry.get('sha256'), str) and
           PROOF.HEX64.fullmatch(entry['sha256']) and
           isinstance(entry.get('receipt_sha256'), str) and
           PROOF.HEX64.fullmatch(entry['receipt_sha256']) and
           isinstance(entry.get('source_zip_sha256'), str) and
           PROOF.HEX64.fullmatch(entry['source_zip_sha256']),
           'DAY_OVERLAY_STATE_ENTRY_INVALID')

    receipt_rel = rel.removesuffix('.parquet') + '.json'
    receipt, receipt_hash = read_bounded(work, receipt_rel, MAX_RECEIPT_BYTES)
    demand(receipt_hash == entry['receipt_sha256'].lower() and
           receipt.get('date') == day_label and
           receipt.get('file') == rel and
           receipt.get('sha256') == entry['sha256'] and
           receipt.get('rows') == entry['rows'] and
           receipt.get('raw_zip_sha256') == entry['source_zip_sha256'] and
           receipt.get('base_dataset_sha256') == BASE_SHA and
           receipt.get('original_Parquet_files_unchanged') is True and
           receipt.get('source_values_adj') == 'none' and
           isinstance(receipt.get('origin'), str) and
           isinstance(receipt.get('calibration'), dict),
           'DAY_OVERLAY_RECEIPT_CHAIN_INVALID')
    result = DAY.inspect_explicit(work, rel, entry['sha256'], day_label,
                                  symbol, row_reader=day_reader)
    demand(result['total_rows_examined'] == entry['rows'],
           'DAY_OVERLAY_ROW_COUNT_DISAGREES_WITH_RECEIPT')

    verified_zip_sha = None
    if raw_zip_relative is not None:
        demand(type(raw_zip_relative) is str and raw_zip_relative.lower().endswith('.zip'),
               'EXPLICIT_RAW_ZIP_PATH_INVALID')
        raw_zip = PROOF._secure_relative(work, raw_zip_relative)
        actual_zip_sha, _ = PROOF._hash_stable_file(raw_zip)
        demand(actual_zip_sha == entry['source_zip_sha256'].lower(),
               'DECLARED_RAW_TDX_ZIP_BYTES_MISMATCH')
        verified_zip_sha = actual_zip_sha

    state_last, state_last_sha = read_bounded(work, 'state.json', MAX_STATE_BYTES)
    receipt_last, receipt_last_sha = read_bounded(work, receipt_rel, MAX_RECEIPT_BYTES)
    demand(state_last_sha == state_hash and state_last == state and
           receipt_last_sha == receipt_hash and receipt_last == receipt,
           'OVERLAY_STATE_OR_RECEIPT_CHANGED_DURING_AUDIT')
    return {
        'status': STATUS,
        'day': day_label, 'symbol': symbol,
        'live_state_bytes_sha256': state_hash,
        'day_overlay_receipt_bytes_sha256': receipt_hash,
        'day_overlay_parquet_bytes_sha256': result['bound_official_day_file_bytes_sha256'],
        'receipt_claimed_raw_tdx_zip_sha256': entry['source_zip_sha256'],
        'day_overlay_rows_verified': result['total_rows_examined'],
        'target_ohlcva': result['target_ohlcva'],
        'day_content_fields_and_target_checked': True,
        'whole_exchange_stock_day_universe_certified': False,
        'provider_identity_authenticated': False,
        'tdx_raw_zip_bytes_verified': verified_zip_sha is not None,
        'tdx_raw_zip_file_bytes_sha256_if_checked': verified_zip_sha,
        'qmt_native_1min_verified': False,
        'market_candidate_validated': False,
        'original_nine_quarantines_cleared': False,
        'market_data_write_authorized': False,
        'market_files_written': False,
        'qmt_history_download_calls': 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--trading-day', required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--raw-zip-relative', default=None)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(args.module_root, args.trading_day, args.symbol,
                                 raw_zip_relative=args.raw_zip_relative),
                         ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (OverlayError, DAY.DayContentError, PROOF.ProofError, ValueError,
            TypeError, OSError, ImportError, RuntimeError, KeyError) as exc:
        print('LIVE_DAY_OVERLAY_REVIEW_REQUIRED: ' + type(exc).__name__ +
              ': ' + str(exc)[:110])
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
