#!/usr/bin/env python3
"""Read-only nine-stock local JSONL census without a missing Nov25 run receipt.

This independent *side evidence* report never invokes (or mocks) the required
original scheduled-run receipt audit and cannot clear production quarantines.
It checks an explicit existing work/qmt_1m_probe directory only, nonrecursive.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import market_local_evidence_inventory_readonly as INVENTORY
import market_nine_quarantine_offline_source_gap_readonly as GAP
import market_native_minute_jsonl_readonly as MINUTE
import market_native_minute_window_readonly as WINDOW
import market_quality_source_proofs as PROOF

FORMAT = 'astock_nine_stage_only_local_probe_census_readonly_v1'
STATUS = 'STAGE_ONLY_LOCAL_PROBES_VERIFIED_OR_MISSING_NOT_ORIGINAL_RECEIPT_AUDIT'
PROBE_SUBDIR = 'qmt_1m_probe'
DAY = GAP.DAY


class StageOnlyProbeError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise StageOnlyProbeError(reason)


def _explicit_root(module_root):
    module = Path(module_root)
    need(module.is_dir() and not module.is_symlink(), 'MODULE_ROOT_INVALID')
    work = module / 'work'
    need(work.is_dir() and not work.is_symlink(), 'WORK_ROOT_INVALID')
    probe = work / PROBE_SUBDIR
    need(probe.is_dir() and not probe.is_symlink() and
         probe.resolve().is_relative_to(work.resolve()),
         'EXPLICIT_PROBE_ROOT_INVALID')
    return probe


def _validated_inventory(root):
    # Existing P3.11 local inventory is a separate byte-level check; it does
    # NOT authenticate a producer or bypass GAP.verify_original().
    result = INVENTORY.inspect(root, 'minute')
    need(type(result) is dict and result.get('status') == INVENTORY.STATUS
         and result.get('kind') == 'minute'
         and type(result.get('files')) is list
         and type(result.get('file_count')) is int
         and result['file_count'] == len(result['files'])
         and result['file_count'] <= GAP.MAX_PROBES
         and result.get('market_files_written') is False
         and result.get('production_quarantine_cleared') is False
         and result.get('qmt_cache_modified') is False
         and result.get('qmt_native_origin_authenticated') is False
         and type(result.get('qmt_download_calls')) is int
         and result['qmt_download_calls'] == 0,
         'LOCAL_PROBE_INVENTORY_SAFETY_GATE_FAILED')
    need(all(type(x) is dict and
             type(x.get('observed_file_bytes')) is int and
             x['observed_file_bytes'] > 0
             for x in result['files']),
         'LOCAL_PROBE_FILE_METADATA_INVALID')
    need(sum(x['observed_file_bytes'] for x in result['files'])
         <= GAP.MAX_PROBE_TOTAL_BYTES,
         'LOCAL_PROBE_TOTAL_SIZE_BUDGET')
    return result


def inspect(module_root):
    root = _explicit_root(module_root)
    before = _validated_inventory(root)
    # Reuse the rigorously bounded JSONL physical-file SHA+minute row+clock
    # checker but DO NOT call the original-run verification entry point.
    sources = [GAP._probe_scope(root, item) for item in before['files']]
    by_symbol = defaultdict(list)
    for source in sources:
        need(type(source) is dict and
             type(source.get('parsed_symbol')) is str and
             source.get('provider_origin_authenticated') is False and
             source.get('official_day_reconciled') is False and
             source.get('purchased_units_calibrated') is False,
             'LOCAL_PROBE_SOURCE_AUTHORITY_INVALID')
        by_symbol[source['parsed_symbol']].append(source)

    nine = []
    statuses = Counter()
    for symbol in sorted(GAP.EXPECTED):
        code = symbol[2:] + '.' + symbol[:2]
        matches = by_symbol.get(code, [])
        if not matches:
            status = 'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY'
        elif len(matches) > 1:
            status = 'MULTIPLE_SAME_SYMBOL_LOCAL_SOURCES_REVIEW_REQUIRED'
        elif matches[0]['target_day_grid_status_if_in_observed_span'] is None:
            status = 'MATCHING_SYMBOL_BUT_NO_20261125_IN_OBSERVED_SPAN'
        else:
            status = ('LOCAL_TARGET_DAY_' +
                      matches[0]['target_day_grid_status_if_in_observed_span']
                      + '_NOT_ADMITTED')
        statuses[status] += 1
        nine.append({
            'quarantined_symbol': symbol,
            'existing_original_quarantine_category':
                'QMT_RAW_ONE_MINUTE_MISSING' if symbol in GAP.MISSING
                else 'OFFICIAL_DAY_OHLC_MISMATCH',
            'matching_validated_local_probe_files': len(matches),
            'local_source_status': status,
            'matching_observed_scopes': [
                {'first_day': s['observed_first_day'],
                 'last_day': s['observed_last_day'],
                 'checked_rows': s['strictly_checked_minute_rows'],
                 'target_day_grid': s['target_day_grid_status_if_in_observed_span']}
                for s in matches],
            'provider_origin_authenticated': False,
            'official_day_reconciled': False,
            'original_quarantine_cleared': False,
        })
    # Rehash the exact same explicit file inventory and reject any difference.
    # This is not a lock; do not claim a snapshot beyond the two checks.
    after = _validated_inventory(root)
    need(before == after, 'LOCAL_PROBE_INVENTORY_CHANGED_DURING_SCAN')

    source_scopes = [{
        'symbol': s['parsed_symbol'],
        'relative_file': s['local_relative_file'],
        'file_sha256': s['local_file_sha256'],
        'first_day': s['observed_first_day'],
        'last_day': s['observed_last_day'],
        'checked_rows': s['strictly_checked_minute_rows'],
        'target_day_grid': s['target_day_grid_status_if_in_observed_span'],
        'provider_origin_authenticated': False,
    } for s in sources]

    need(len(nine) == 9 and
         {x['quarantined_symbol'] for x in nine} == GAP.EXPECTED,
         'ORIGINAL_NINE_FIXED_SYMBOLS_INVALID')
    return {
        'format': FORMAT, 'status': STATUS, 'day': DAY,
        'explicit_probe_directory_relative_to_work': PROBE_SUBDIR,
        'probe_directory_recursively_searched': False,
        'existing_probe_files_content_checked': len(sources),
        'probe_source_scopes': source_scopes,
        'nine_quarantine_local_evidence': nine,
        'nine_local_status_counts': dict(sorted(statuses.items())),
        'local_file_inventory_unchanged_during_scan': True,
        'local_files_provider_authenticated': False,
        'original_run_receipt_authenticated': False,
        'original_run_stage_link_verified': False,
        'original_receipt_sha256_expected_but_not_proved': GAP.RUN_SHA,
        'original_quarantines_cleared': False,
        'production_merge_authorized': False,
        'market_files_written': False,
        'qmt_cache_queried_or_modified': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        print(json.dumps(inspect(args.module_root), indent=2,
                         sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (StageOnlyProbeError, INVENTORY.InventoryError,
            GAP.GapError, MINUTE.NativeMinuteError, WINDOW.WindowError,
            PROOF.ProofError, ValueError, OSError, TypeError,
            RuntimeError, KeyError) as exc:
        # Never disclose any arbitrary private source paths or file contents.
        print('STAGE_ONLY_LOCAL_PROBE_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
