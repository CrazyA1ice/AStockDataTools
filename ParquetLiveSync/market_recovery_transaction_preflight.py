#!/usr/bin/env python3
"""Read-only physical-target transaction blueprint for evidence-only recovery plans.

No minute payload, backup, staging artifact, CAS lock or commit is performed.
The deterministic eight-period footprint is NOT approval to change the files.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import stat

import market_recovery_review_plan as REVIEW

FORMAT = 'astock_recovery_transaction_preflight_readonly_v1'
STATUS = 'TRANSACTION_BLUEPRINT_BLOCKED_NO_STAGING_OR_COMMIT'
PERIODS = ('1min', '5min', '15min', '30min', '60min', 'day', 'week', 'month')
MAX_TARGETS = 256

BLOCKERS = (
    'ORIGINAL_PRODUCER_QUARANTINE_UNRESOLVED',
    'NATIVE_QMT_MINUTE_PAYLOAD_AND_LINEAGE_UNVERIFIED',
    'INDEPENDENT_OFFICIAL_DAY_AND_STOCK_UNIVERSE_UNAUTHENTICATED',
    'PURCHASED_MINUTE_CALIBRATION_AND_SIX_FIELD_REPLAY_MISSING',
    'EIGHT_PERIOD_CONTENT_AND_AGGREGATION_NOT_REVALIDATED',
    'VERSIONED_PRIVATE_CANDIDATE_NOT_MATERIALIZED',
    'PRECHANGE_BACKUP_NOT_CREATED_AND_RESTORATION_NOT_TESTED',
    'ATOMIC_COMPARE_AND_SWAP_COMMIT_NOT_AUTHORIZED',
)

class PreflightError(ValueError):
    pass

def need(ok, message):
    if not ok:
        raise PreflightError(message)

def _target_rel(day: str, period: str, layout_year: int) -> str:
    d = date.fromisoformat(day)
    need(d.year <= layout_year, 'REQUEST_DAY_AFTER_DECLARED_LAYOUT_YEAR')
    name = (f'{d.year}.parquet' if d.year < layout_year else
            f'{d.year}-{d.month:02}.parquet')
    return f'{period}/{name}'

def _physical_targets(snapshot_root: Path, targets):
    """Optional read-only file-byte observation; does not create backups.

    Use the actual local_layout storage convention; missing target is reported
    as a blocker, not repaired. Existing targets are SHA-checked individually.
    """
    import local_layout as L
    import market_quality_source_proofs as PROOF
    base = L.storage_root(snapshot_root, require_all=True)
    states = {}
    for relative in targets:
        path = base
        for component in relative.split('/'):
            path = path / component
            need(not path.is_symlink(), 'TARGET_SYMLINK_FORBIDDEN')
        if not path.exists():
            states[relative] = {'state': 'ABSENT_BLOCKED', 'bytes_sha256': None}
            continue
        need(path.is_file() and stat.S_ISREG(path.stat().st_mode),
             'TARGET_NOT_REGULAR_FILE')
        actual, nbytes = PROOF._hash_stable_file(path)
        states[relative] = {
            'state': 'EXISTING_BYTES_OBSERVED_NOT_BACKED_UP',
            'bytes_sha256': actual, 'bytes': nbytes,
        }
    return states

def build_blueprint(review_plan, *, layout_year: int, target_root=None):
    """Pure without target_root; optional path reads are strictly observational."""
    REVIEW.validate_plan(review_plan)
    need(type(layout_year) is int and 1900 <= layout_year <= 2200,
         'INVALID_LAYOUT_YEAR')
    requests = review_plan['requests']
    need(len(requests) <= REVIEW.MAX_CASES, 'TOO_MANY_REVIEW_REQUESTS')
    targets = defaultdict(set)
    for r in requests:
        scope = r['scope']
        for p in PERIODS:
            targets[_target_rel(scope['trading_day'], p, layout_year)].add(
                r['review_request_id'])
    need(len(targets) <= MAX_TARGETS, 'TARGET_FILE_BUDGET_EXCEEDED')
    observed = (_physical_targets(Path(target_root), sorted(targets))
                if target_root is not None else {})
    records = []
    for relative, ids in sorted(targets.items()):
        observation = observed.get(relative, {
            'state': 'NOT_INSPECTED_NO_TARGET_ROOT', 'bytes_sha256': None})
        records.append({
            'relative_path': relative,
            'affected_review_request_ids': sorted(ids),
            'file_observation': observation,
            'prechange_backup_created': False,
            'restore_verified': False,
            'compare_and_swap_authorized': False,
            'write_authorized': False,
        })
    report = {
        'format': FORMAT, 'status': STATUS,
        'source_review_plan_sha256': review_plan['plan_sha256'],
        'original_backlog_sha256': review_plan['original_backlog_sha256'],
        'declared_layout_year': layout_year,
        'recovery_review_request_count': len(requests),
        'eight_period_target_file_count': len(records),
        'physical_target_checks_requested': target_root is not None,
        'physical_target_files_checked': len(observed),
        'target_files': records,
        'transaction_gates_missing': list(BLOCKERS),
        'transaction_status': 'BLOCKED_NOT_A_MARKET_CANDIDATE',
        'native_minute_payload_present': False,
        'private_candidate_materialized': False,
        'private_backup_materialized': False,
        'rollback_tested': False,
        'independent_source_identity_authenticated': False,
        'official_stock_day_universe_certified': False,
        'eight_period_data_validated': False,
        'source_snapshot_is_rollback_backup': False,
        'staging_bytes_written': 0,
        'production_bytes_written': 0,
        'market_parquet_or_h5_write_authorized': False,
        'qmt_cache_write_authorized': False,
        'qmt_history_download_authorized': False,
        'qmt_history_download_calls': 0,
        'producer_quarantine_cleared': False,
        'market_quality_cleared': False,
        'production_merge_authorized': False,
    }
    report['blueprint_sha256'] = REVIEW.digest(report)
    return report

def inspect(module_root, start_day, end_day, *, layout_year,
            target_root=None, max_stock_days=64, review_reader=None):
    fetch = review_reader or REVIEW.inspect
    plan = fetch(module_root, start_day, end_day,
                 max_stock_days=max_stock_days)
    return build_blueprint(plan, layout_year=layout_year, target_root=target_root)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    p.add_argument('--start-day', required=True)
    p.add_argument('--end-day', required=True)
    p.add_argument('--layout-year', type=int, required=True)
    p.add_argument('--target-root', type=Path)
    p.add_argument('--max-stock-days', type=int, default=64)
    p.add_argument('--summary-only', action='store_true')
    args = p.parse_args(argv)
    try:
        result = inspect(args.module_root, args.start_day, args.end_day,
                         layout_year=args.layout_year,
                         target_root=args.target_root,
                         max_stock_days=args.max_stock_days)
        display = ({k: v for k, v in result.items() if k != 'target_files'}
                   if args.summary_only else result)
        print(json.dumps(display, ensure_ascii=False, indent=2,
                         sort_keys=True, allow_nan=False))
        return 0
    except (PreflightError, REVIEW.PlanError, ValueError, OSError,
            ImportError, RuntimeError, TypeError, KeyError) as exc:
        print('RECOVERY_TRANSACTION_PREFLIGHT_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3

if __name__ == '__main__':
    raise SystemExit(main())
