#!/usr/bin/env python3
"""Read-only 2026-11-25 nine-quarantine source gap assessment.

Recheck pinned original producer receipt and ALL explicit existing probe JSONLs.
No xtquant, download, disk search, production data writing or source promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json

import audit_market_quarantine_readonly as AUDIT
import market_local_evidence_inventory_readonly as INVENTORY
import market_native_minute_jsonl_readonly as MINUTE
import market_native_minute_window_readonly as WINDOW
import market_quality_source_proofs as PROOF

FORMAT = 'astock_nine_quarantine_offline_source_gap_readonly_v1'
STATUS = 'ORIGINAL_NINE_PRODUCER_QUARANTINES_RETAINED_LOCAL_SOURCE_GAPS_ONLY'
DAY = '2026-11-25'
RUN_SHA = '72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837'
MISSING = tuple('SZ300' + str(i) for i in range(119, 126))
MISMATCH = ('SH605336', 'SZ300462')
EXPECTED = frozenset(MISSING + MISMATCH)
MAX_PROBES = 16
MAX_PROBE_TOTAL_BYTES = 64 * 1024 * 1024


class GapError(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise GapError(why)


def verify_original(module_root, *, audit_reader=None):
    reader = audit_reader if audit_reader is not None else AUDIT.audit
    result = reader(module_root, DAY, RUN_SHA, verify_parquet=True)
    need(type(result) is dict and result.get('status') == 'METADATA_MATCH_QUARANTINE_RETAINED'
         and result.get('day') == DAY
         and result.get('run_receipt_sha256') == RUN_SHA
         and result.get('accepted') == 5206 and type(result.get('accepted')) is int
         and result.get('quarantined') == 9 and type(result.get('quarantined')) is int
         and result.get('expected') == 5215 and type(result.get('expected')) is int
         and result.get('parquet_content_sha_verified') is True
         and result.get('data_quality_cleared') is False
         and type(result.get('stocks')) is list and len(result['stocks']) == 9,
         'PINNED_ORIGINAL_PRODUCER_RECEIPT_INVALID')
    observed = {}
    for entry in result['stocks']:
        need(type(entry) is dict and type(entry.get('symbol')) is str
             and type(entry.get('category')) is str, 'ORIGINAL_QUARANTINE_RECORD_INVALID')
        symbol = entry['symbol']
        need(symbol in EXPECTED and symbol not in observed, 'ORIGINAL_NINE_SYMBOLS_CHANGED')
        observed[symbol] = entry['category']
    need(set(observed) == EXPECTED and
         all(observed[s] == 'QMT_RAW_ONE_MINUTE_MISSING' for s in MISSING) and
         all(observed[s] == 'OFFICIAL_DAY_OHLC_MISMATCH' for s in MISMATCH),
         'ORIGINAL_NINE_REASON_CATEGORIES_CHANGED')
    return observed, result


def _probe_scope(root, record, *, window_reader=None):
    relative, expected_sha = record['relative_path'], record['observed_local_file_sha256']
    need(type(relative) is str and relative.endswith('.jsonl') and
         type(expected_sha) is str and bool(PROOF.HEX64.fullmatch(expected_sha))
         and type(record.get('observed_file_bytes')) is int
         and 0 < record['observed_file_bytes'] <= MINUTE.MAX_BYTES
         and record.get('contents_validated') is False
         and record.get('source_provider_authenticated') is False,
         'PROBE_INVENTORY_ENTRY_SCOPE_INVALID')
    path = PROOF._secure_relative(root, relative)
    need(0 < path.stat().st_size <= MINUTE.MAX_BYTES, 'PROBE_SIZE_OUTSIDE_NATIVE_BUDGET')
    first_day, last_day, symbol = None, None, None
    count = 0
    # Parse a bounded existing export to derive the date and stock scope from
    # actual contents rather than assuming filename-declared stock/date ranges.
    for row in MINUTE._file_rows(path):
        count += 1
        need(count <= MINUTE.MAX_ROWS, 'PROBE_ROW_BUDGET')
        current = MINUTE.normalize_symbol(row['symbol'])
        stamp = MINUTE.parse_stamp(row['datetime_cn'])
        day = stamp.date().isoformat()
        need(symbol is None or current == symbol, 'PROBE_MIXED_SYMBOLS')
        symbol = current
        first_day = min(first_day, day) if first_day is not None else day
        last_day = max(last_day, day) if last_day is not None else day
    need(symbol is not None and count > 0, 'PROBE_NO_ROWS')
    reader = window_reader if window_reader is not None else WINDOW.inspect
    checked = reader(root, relative, expected_sha, symbol, first_day, last_day)
    need(type(checked) is dict and checked.get('status') == WINDOW.STATUS
         and checked.get('declared_symbol') == symbol
         and checked.get('physical_local_file_sha256') == expected_sha
         and checked.get('physical_local_file_bytes') == record['observed_file_bytes']
         and checked.get('source_file_bytes_verified') is True
         and checked.get('rows_structurally_and_numerically_validated') == count
         and type(checked.get('days')) is list
         and checked.get('production_quarantine_cleared') is False
         and checked.get('production_merge_authorized') is False
         and checked.get('market_files_written') is False
         and checked.get('native_qmt_provider_origin_authenticated') is False
         and checked.get('qmt_cache_modified') is False
         and checked.get('qmt_history_download_calls') == 0,
         'PROBE_WINDOW_CONTENT_OR_SCOPE_UNVERIFIED')
    day_status = next((d['grid_status'] for d in checked['days']
                       if d['day'] == DAY), None)
    return {
        'local_relative_file': relative,
        'local_file_sha256': expected_sha,
        'parsed_symbol': symbol,
        'observed_first_day': first_day,
        'observed_last_day': last_day,
        'strictly_checked_minute_rows': count,
        'target_day_grid_status_if_in_observed_span': day_status,
        'provider_origin_authenticated': False,
        'purchased_units_calibrated': False,
        'official_day_reconciled': False,
    }


def inspect(module_root, minute_root, *, audit_reader=None, inventory_reader=None,
            window_reader=None):
    root = Path(minute_root)
    need(root.is_dir() and not root.is_symlink(), 'EXPLICIT_LOCAL_PROBE_ROOT_INVALID')
    original, receipt = verify_original(module_root, audit_reader=audit_reader)
    inventory = (inventory_reader or INVENTORY.inspect)(root, 'minute')
    need(type(inventory) is dict and inventory.get('status') == INVENTORY.STATUS
         and inventory.get('kind') == 'minute'
         and type(inventory.get('files')) is list
         and type(inventory.get('file_count')) is int
         and inventory['file_count'] == len(inventory['files'])
         and inventory['file_count'] <= MAX_PROBES
         and inventory.get('market_files_written') is False
         and inventory.get('production_quarantine_cleared') is False
         and inventory.get('qmt_cache_modified') is False
         and type(inventory.get('qmt_download_calls')) is int
         and inventory.get('qmt_download_calls') == 0
         and inventory.get('qmt_native_origin_authenticated') is False,
         'EXPLICIT_PROBE_INVENTORY_INVALID')
    need(sum(x.get('observed_file_bytes', 0) for x in inventory['files'])
         <= MAX_PROBE_TOTAL_BYTES, 'LOCAL_PROBES_TOTAL_SIZE_BUDGET')
    sources = [_probe_scope(root, record, window_reader=window_reader)
               for record in inventory['files']]
    by_stock = defaultdict(list)
    for source in sources:
        by_stock[source['parsed_symbol']].append(source)
    results = []
    status_counts = Counter()
    for symbol in sorted(original):
        code = symbol[2:] + '.' + symbol[:2]
        matches = by_stock.get(code, [])
        if not matches:
            status = 'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY'
        elif len(matches) > 1:
            status = 'MULTIPLE_SAME_SYMBOL_LOCAL_SOURCES_REVIEW_REQUIRED'
        elif matches[0]['target_day_grid_status_if_in_observed_span'] is None:
            status = 'MATCHING_SYMBOL_BUT_NO_20261125_IN_OBSERVED_SPAN'
        else:
            status = 'LOCAL_TARGET_DAY_' + matches[0]['target_day_grid_status_if_in_observed_span'] + '_NOT_ADMITTED'
        status_counts[status] += 1
        results.append({
            'quarantined_symbol': symbol,
            'quarantine_reason_category': original[symbol],
            'existing_explicit_probe_matches': len(matches),
            'offline_local_source_status': status,
            'matching_sources': matches,
            'independent_official_day_quality_confirmed': False,
            'native_provider_authenticity_certified': False,
            'producer_quarantine_closed': False,
            'market_repair_authorized': False,
        })
    # Detect original receipt changes during any external file read.
    original_again, receipt_again = verify_original(module_root, audit_reader=audit_reader)
    need(original_again == original and receipt_again == receipt,
         'ORIGINAL_QUARANTINE_RECEIPT_CHANGED_DURING_OFFLINE_SCAN')
    scope = {'run_receipt_sha256': RUN_SHA, 'day': DAY,
             'probe_source_digests': sorted(x['local_file_sha256'] for x in sources),
             'quarantine_source_statuses': [(x['quarantined_symbol'], x['offline_local_source_status'])
                                            for x in results]}
    return {
        'format': FORMAT, 'status': STATUS, 'day': DAY,
        'pinned_run_receipt_sha256': RUN_SHA,
        'probe_directory_explicit_not_recursive': True,
        'existing_probe_files_content_checked': len(sources),
        'existing_probe_source_scopes': sources,
        'original_accepted_stock_days': 5206,
        'original_expected_stock_days': 5215,
        'original_quarantined_stock_days': 9,
        'original_categories': dict(sorted(Counter(original.values()).items())),
        'nine_quarantine_source_status_counts': dict(sorted(status_counts.items())),
        'stocks': results,
        'diagnostic_scope_sha256': PROOF.digest(scope),
        'physical_source_lock_held': False,
        'supplier_origin_authenticated': False,
        'calibration_approved_or_applied': False,
        'official_six_field_quality_passed': False,
        'original_quarantines_cleared': False,
        'production_merge_authorized': False,
        'market_files_written': False,
        'qmt_cache_queried_or_modified': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    p.add_argument('--minute-evidence-root', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.module_root, a.minute_evidence_root),
                         indent=2, ensure_ascii=False, sort_keys=True,
                         allow_nan=False))
        return 0
    except (GapError, AUDIT.EvidenceError, INVENTORY.InventoryError,
            MINUTE.NativeMinuteError, WINDOW.WindowError, PROOF.ProofError,
            ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
        print('NINE_QUARANTINE_OFFLINE_SOURCE_GAP_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
