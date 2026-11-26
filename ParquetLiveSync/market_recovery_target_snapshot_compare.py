#!/usr/bin/env python3
"""SHA-pinned read-only transaction-footprint comparisons, never a CAS approval.

Prior and current blueprints are observation *claims*, not independently
signed backups, locks, rollback images or verified complete market data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

import market_recovery_transaction_preflight as TX
import market_recovery_review_plan as REVIEW

FORMAT = 'astock_recovery_target_snapshot_comparison_v1'
STATUS = 'TARGET_SNAPSHOT_DIFFERENCE_REVIEW_ONLY_NO_CAS_OR_COMMIT'
MAX_PRIOR_BYTES = 4 * 1024 * 1024
STATES = frozenset((
    'NOT_INSPECTED_NO_TARGET_ROOT',
    'ABSENT_BLOCKED',
    'EXISTING_BYTES_OBSERVED_NOT_BACKED_UP',
))
DRIFT = frozenset(('FILE_APPEARED_SINCE_PRIOR',
                   'FILE_DISAPPEARED_SINCE_PRIOR',
                   'FILE_BYTES_CHANGED_SINCE_PRIOR'))
NO_AUTHORITY = (
    'native_minute_payload_present', 'private_candidate_materialized',
    'private_backup_materialized', 'rollback_tested',
    'independent_source_identity_authenticated',
    'official_stock_day_universe_certified', 'eight_period_data_validated',
    'source_snapshot_is_rollback_backup',
    'market_parquet_or_h5_write_authorized', 'qmt_cache_write_authorized',
    'qmt_history_download_authorized', 'producer_quarantine_cleared',
    'market_quality_cleared', 'production_merge_authorized',
)


class SnapshotError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise SnapshotError(reason)


def valid_sha(value):
    return REVIEW.valid_sha(value)


def _strict_pairs(pairs):
    seen = {}
    for key, value in pairs:
        need(key not in seen, 'DUPLICATE_SNAPSHOT_JSON_KEY')
        seen[key] = value
    return seen


def validate_blueprint(blueprint):
    """Verify schema, diagnostic digest, physical observation contracts and scope.

    The canonical digest catches accidental edits, NOT deliberate forgery.
    Calling this routine never turns a claimed file digest into a signature.
    """
    need(type(blueprint) is dict and blueprint.get('format') == TX.FORMAT
         and blueprint.get('status') == TX.STATUS,
         'SNAPSHOT_FORMAT_OR_STATUS_INVALID')
    seal = blueprint.get('blueprint_sha256')
    need(valid_sha(seal) and
         REVIEW.digest({k: v for k, v in blueprint.items()
                        if k != 'blueprint_sha256'}) == seal.lower(),
         'SNAPSHOT_BLUEPRINT_DIGEST_CHANGED')
    need(all(blueprint.get(k) is False for k in NO_AUTHORITY),
         'SNAPSHOT_FORGED_MARKET_AUTHORITY')
    need(all(blueprint.get(k) == 0 for k in
             ('staging_bytes_written', 'production_bytes_written',
              'qmt_history_download_calls')) and
         blueprint.get('transaction_status') ==
         'BLOCKED_NOT_A_MARKET_CANDIDATE',
         'SNAPSHOT_UNEXPECTED_MUTATION_OR_TRANSACTION_STATUS')
    need(blueprint.get('transaction_gates_missing') == list(TX.BLOCKERS),
         'SNAPSHOT_MISSING_OR_CHANGED_TRANSACTION_GATES')
    need(valid_sha(blueprint.get('source_review_plan_sha256')) and
         valid_sha(blueprint.get('original_backlog_sha256')),
         'SNAPSHOT_SOURCE_EVIDENCE_SHA_MISSING')
    year = blueprint.get('declared_layout_year')
    need(type(year) is int and 1900 <= year <= 2200,
         'SNAPSHOT_LAYOUT_YEAR_INVALID')
    nrequests = blueprint.get('recovery_review_request_count')
    need(type(nrequests) is int and 0 <= nrequests <= REVIEW.MAX_CASES,
         'SNAPSHOT_REQUEST_COUNT_INVALID')
    target_files = blueprint.get('target_files')
    need(type(target_files) is list and len(target_files) <= TX.MAX_TARGETS
         and blueprint.get('eight_period_target_file_count') == len(target_files),
         'SNAPSHOT_TARGET_COUNT_INVALID')
    inspected = blueprint.get('physical_target_checks_requested')
    checked = blueprint.get('physical_target_files_checked')
    need(type(inspected) is bool and type(checked) is int and
         checked == (len(target_files) if inspected else 0),
         'SNAPSHOT_PHYSICAL_CHECK_SCOPE_INVALID')

    paths = []
    id_counts = Counter()
    id_periods = defaultdict(set)
    id_shards = defaultdict(set)
    states = {}
    for target in target_files:
        need(type(target) is dict and set(target) == {
             'relative_path', 'affected_review_request_ids',
             'file_observation', 'prechange_backup_created',
             'restore_verified', 'compare_and_swap_authorized',
             'write_authorized'}, 'SNAPSHOT_TARGET_SHAPE_CHANGED')
        need(all(target[k] is False for k in
                 ('prechange_backup_created', 'restore_verified',
                  'compare_and_swap_authorized', 'write_authorized')),
             'SNAPSHOT_TARGET_FORGED_COMMIT_OR_BACKUP')
        path = target['relative_path']
        need(type(path) is str and '\\' not in path and '..' not in path and
             bool(re.fullmatch(r'(1min|5min|15min|30min|60min|day|week|month)/'
                               r'(19\d{2}|20\d{2}|21\d{2}|2200)'
                               r'(-(?:0[1-9]|1[0-2]))?\.parquet', path)),
             'SNAPSHOT_TARGET_PATH_INVALID')
        period, name = path.split('/')
        fileyear = int(name[:4])
        month = name[4] == '-'
        need(fileyear <= year and (month == (fileyear == year)),
             'SNAPSHOT_TARGET_LAYOUT_DISAGREES_WITH_DECLARED_YEAR')
        ids = target['affected_review_request_ids']
        need(type(ids) is list and ids == sorted(set(ids)) and ids and
             all(valid_sha(x) for x in ids),
             'SNAPSHOT_TARGET_REVIEW_IDS_INVALID')
        for x in ids:
            id_counts[x] += 1
            id_periods[x].add(period)
            id_shards[x].add(name)
        paths.append(path)
        obs = target['file_observation']
        need(type(obs) is dict and obs.get('state') in STATES,
             'SNAPSHOT_FILE_OBSERVATION_INVALID')
        state = obs['state']
        if state == 'EXISTING_BYTES_OBSERVED_NOT_BACKED_UP':
            need(set(obs) == {'state', 'bytes_sha256', 'bytes'} and
                 valid_sha(obs['bytes_sha256']) and
                 type(obs['bytes']) is int and 0 < obs['bytes'] <= (1 << 30),
                 'SNAPSHOT_OBSERVED_FILE_SHA_OR_SIZE_INVALID')
        else:
            need(set(obs) == {'state', 'bytes_sha256'} and
                 obs['bytes_sha256'] is None,
                 'SNAPSHOT_UNOBSERVED_OR_MISSING_SHA_FORGED')
        need((state == 'NOT_INSPECTED_NO_TARGET_ROOT') is (not inspected),
             'SNAPSHOT_OBSERVATION_SCOPE_INCONSISTENT')
        states[path] = obs
    need(paths == sorted(set(paths)), 'SNAPSHOT_DUPLICATED_OR_UNSORTED_TARGETS')
    need((len(id_counts) == nrequests and all(
         id_counts[i] == len(TX.PERIODS) and id_periods[i] == set(TX.PERIODS)
         for i in id_counts)) or
         (nrequests == 0 and not id_counts and not paths),
         'SNAPSHOT_REVIEW_IDS_EIGHT_PERIOD_CONSERVATION_FAILED')
    # One review request represents one stock-day and must map to the SAME
    # year/month shard across all eight periods, not eight unrelated shards.
    # The blueprint alone cannot prove that shard matches the original day;
    # that stronger claim belongs to its validated source review plan.
    need(all(len(shards) == 1 for shards in id_shards.values()),
         'SNAPSHOT_REVIEW_REQUEST_CROSS_PERIOD_SHARD_MISMATCH')
    return states


def compare(prior, current):
    """Observe two timepoint evidence snapshots, never certify atomic updates."""
    old = validate_blueprint(prior)
    new = validate_blueprint(current)
    for k in ('source_review_plan_sha256', 'original_backlog_sha256',
              'declared_layout_year', 'recovery_review_request_count'):
        need(prior[k] == current[k], 'SNAPSHOT_SOURCE_PLAN_OR_LAYOUT_CHANGED_NEW_BASELINE_REQUIRED')
    need(set(old) == set(new) and
         all(next(t['affected_review_request_ids'] for t in prior['target_files']
                  if t['relative_path'] == path) ==
             next(t['affected_review_request_ids'] for t in current['target_files']
                  if t['relative_path'] == path) for path in old),
         'SNAPSHOT_REVIEW_TARGET_SCOPE_CHANGED_NEW_BASELINE_REQUIRED')
    differences = []
    for path in sorted(old):
        before, after = old[path], new[path]
        bs, cs = before['state'], after['state']
        if bs == 'NOT_INSPECTED_NO_TARGET_ROOT' and cs == bs:
            condition = 'NEITHER_TIMEPOINT_PHYSICALLY_OBSERVED'
        elif 'NOT_INSPECTED_NO_TARGET_ROOT' in (bs, cs):
            condition = 'ONE_TIMEPOINT_NOT_OBSERVED_CANNOT_COMPARE'
        elif bs == 'ABSENT_BLOCKED' and cs == bs:
            condition = 'ABSENT_AT_BOTH_TIMEPOINTS_STILL_BLOCKED'
        elif bs == 'ABSENT_BLOCKED':
            condition = 'FILE_APPEARED_SINCE_PRIOR'
        elif cs == 'ABSENT_BLOCKED':
            condition = 'FILE_DISAPPEARED_SINCE_PRIOR'
        elif before['bytes_sha256'].lower() == after['bytes_sha256'].lower():
            # SHA256 of the same physical bytes necessarily has the same size.
            # A re-sealed JSON claiming otherwise is contradictory evidence.
            need(before['bytes'] == after['bytes'],
                 'SNAPSHOT_IDENTICAL_SHA_DIFFERENT_FILE_SIZE')
            condition = 'OBSERVED_FILE_BYTES_SHA_UNCHANGED_BUT_NOT_LOCKED'
        else:
            condition = 'FILE_BYTES_CHANGED_SINCE_PRIOR'
        differences.append({
            'relative_path': path,
            'comparison_state': condition,
            'prior_observed_bytes_sha256': before['bytes_sha256'],
            'current_observed_bytes_sha256': after['bytes_sha256'],
            'old_or_new_file_is_validated_backup': False,
            'atomic_write_or_cas_authorized': False,
        })
    counts = dict(sorted(Counter(d['comparison_state'] for d in differences).items()))
    physical_pairs = sum(counts.get(k, 0) for k in (
        'OBSERVED_FILE_BYTES_SHA_UNCHANGED_BUT_NOT_LOCKED',
        'FILE_BYTES_CHANGED_SINCE_PRIOR'))
    unobserved_pairs = sum(counts.get(k, 0) for k in (
        'NEITHER_TIMEPOINT_PHYSICALLY_OBSERVED',
        'ONE_TIMEPOINT_NOT_OBSERVED_CANNOT_COMPARE'))
    absent_pairs = sum(counts.get(k, 0) for k in (
        'ABSENT_AT_BOTH_TIMEPOINTS_STILL_BLOCKED',
        'FILE_APPEARED_SINCE_PRIOR', 'FILE_DISAPPEARED_SINCE_PRIOR'))
    need(physical_pairs + unobserved_pairs + absent_pairs == len(differences),
         'SNAPSHOT_COMPARISON_COVERAGE_INCOMPLETE')
    result = {
        'format': FORMAT, 'status': STATUS,
        'source_review_plan_sha256': current['source_review_plan_sha256'],
        'prior_blueprint_sha256': prior['blueprint_sha256'],
        'current_blueprint_sha256': current['blueprint_sha256'],
        'compared_target_file_count': len(differences),
        'difference_counts': counts,
        'physical_sha_pairs_compared': physical_pairs,
        'not_observed_at_one_or_both_timepoints': unobserved_pairs,
        'absent_at_one_or_both_timepoints': absent_pairs,
        'full_physical_sha_pair_coverage': bool(differences) and
            physical_pairs == len(differences),
        'has_observed_file_drift': any(k in counts for k in DRIFT),
        'all_existing_physical_targets_hash_equal_at_observation_times':
            bool(differences) and all(
                d['comparison_state'] ==
                'OBSERVED_FILE_BYTES_SHA_UNCHANGED_BUT_NOT_LOCKED'
                for d in differences),
        'differences': differences,
        'physical_source_lock_held': False,
        'prior_blueprint_is_provider_signature': False,
        'compare_and_swap_authorized': False,
        'backup_materialized_or_restoration_tested': False,
        'original_producer_quarantines_cleared': False,
        'qmt_history_download_calls': 0,
        'staging_bytes_written': 0,
        'market_files_written': False,
        'production_merge_authorized': False,
    }
    result['comparison_sha256'] = REVIEW.digest(result)
    return result


def read_prior(root: Path, relative: str, expected_sha256: str):
    """Require SHA of actual prior JSON bytes and integrity of its inner report."""
    need(valid_sha(expected_sha256), 'PRIOR_BLUEPRINT_EXPECTED_SHA_INVALID')
    root = Path(root)
    need(root.is_dir() and not root.is_symlink(), 'PRIOR_BLUEPRINT_ROOT_INVALID')
    import market_quality_source_proofs as PROOF
    path = PROOF._secure_relative(root, relative)
    # Refuse an oversized prior blueprint before hashing large market files.
    need(0 < path.stat().st_size <= MAX_PRIOR_BYTES,
         'PRIOR_BLUEPRINT_FILE_SHA_OR_SIZE_MISMATCH')
    actual, size = PROOF._hash_stable_file(path)
    need(size <= MAX_PRIOR_BYTES and actual == expected_sha256.lower(),
         'PRIOR_BLUEPRINT_FILE_SHA_OR_SIZE_MISMATCH')
    raw = path.read_bytes()
    after, size_after = PROOF._hash_stable_file(path)
    need(after == actual == sha256(raw).hexdigest() and
         size == size_after == len(raw), 'PRIOR_BLUEPRINT_CHANGED_DURING_READ')
    try:
        loaded = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_strict_pairs)
    except SnapshotError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise SnapshotError('PRIOR_BLUEPRINT_JSON_INVALID') from exc
    validate_blueprint(loaded)
    return loaded


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    p.add_argument('--start-day', required=True)
    p.add_argument('--end-day', required=True)
    p.add_argument('--layout-year', type=int, required=True)
    p.add_argument('--target-root', type=Path)
    p.add_argument('--prior-root', type=Path)
    p.add_argument('--prior-relative')
    p.add_argument('--prior-file-sha256')
    p.add_argument('--max-stock-days', type=int, default=64)
    p.add_argument('--summary-only', action='store_true')
    args = p.parse_args(argv)
    try:
        prior_args = (args.prior_root, args.prior_relative, args.prior_file_sha256)
        need(all(x is None for x in prior_args) or all(x is not None for x in prior_args),
             'PRIOR_BLUEPRINT_ARGS_ALL_OR_NONE')
        current = TX.inspect(args.module_root, args.start_day, args.end_day,
                             layout_year=args.layout_year,
                             target_root=args.target_root,
                             max_stock_days=args.max_stock_days)
        validate_blueprint(current)
        if all(x is not None for x in prior_args):
            result = compare(read_prior(args.prior_root, args.prior_relative,
                                        args.prior_file_sha256), current)
        else:
            result = {
                'format': FORMAT,
                'status': 'NO_PRIOR_BLUEPRINT_SUPPLIED_COMPARISON_NOT_PERFORMED',
                'current_blueprint_sha256': current['blueprint_sha256'],
                'source_review_plan_sha256': current['source_review_plan_sha256'],
                'target_files': current['target_files'],
                'target_file_count': current['eight_period_target_file_count'],
                'market_files_written': False,
                'production_merge_authorized': False,
                'physical_source_lock_held': False,
                'qmt_history_download_calls': 0,
            }
        if args.summary_only:
            result = {k: v for k, v in result.items()
                      if k not in ('differences', 'target_files')}
        print(json.dumps(result, ensure_ascii=False, indent=2,
                         sort_keys=True, allow_nan=False))
        return 0
    except (SnapshotError, TX.PreflightError, REVIEW.PlanError,
            ValueError, OSError, TypeError, KeyError,
            RuntimeError, ImportError) as exc:
        print('TARGET_SNAPSHOT_COMPARISON_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
