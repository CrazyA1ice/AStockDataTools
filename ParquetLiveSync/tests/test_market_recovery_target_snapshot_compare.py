"""Transaction footprint comparisons are read-only and never imply CAS approval."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import StringIO
from pathlib import Path
import contextlib
import json
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_market_recovery_review_plan import fixture
import market_recovery_review_plan as R
import market_recovery_transaction_preflight as TX
import market_recovery_target_snapshot_compare as S


def baseline():
    return TX.build_blueprint(R.build_review_plan(fixture()), layout_year=2026)


def seal(report):
    report['blueprint_sha256'] = R.digest({k: v for k, v in report.items()
                                           if k != 'blueprint_sha256'})
    return report


def observed(report, sha='a' * 64, *, nbytes=400):
    report = deepcopy(report)
    report['physical_target_checks_requested'] = True
    report['physical_target_files_checked'] = len(report['target_files'])
    for i, item in enumerate(report['target_files']):
        item['file_observation'] = {
            'state': 'EXISTING_BYTES_OBSERVED_NOT_BACKED_UP',
            'bytes_sha256': sha, 'bytes': nbytes,
        }
    return seal(report)


def missing(report):
    report = deepcopy(report)
    report['physical_target_checks_requested'] = True
    report['physical_target_files_checked'] = len(report['target_files'])
    for item in report['target_files']:
        item['file_observation'] = {'state': 'ABSENT_BLOCKED', 'bytes_sha256': None}
    return seal(report)


class SnapshotComparisonTests(unittest.TestCase):
    def test_default_unobserved_is_not_mistaken_for_byte_identity(self):
        r = baseline()
        out = S.compare(r, r)
        self.assertEqual(out['compared_target_file_count'], 8)
        self.assertEqual(out['difference_counts'], {'NEITHER_TIMEPOINT_PHYSICALLY_OBSERVED': 8})
        self.assertFalse(out['all_existing_physical_targets_hash_equal_at_observation_times'])
        self.assertFalse(out['has_observed_file_drift'])
        self.assertFalse(out['production_merge_authorized'])
        self.assertFalse(out['physical_source_lock_held'])
        self.assertFalse(out['backup_materialized_or_restoration_tested'])

    def test_identical_observed_sha_still_not_locked_or_commit_approved(self):
        r = observed(baseline())
        out = S.compare(r, r)
        self.assertEqual(out['difference_counts'],
                         {'OBSERVED_FILE_BYTES_SHA_UNCHANGED_BUT_NOT_LOCKED': 8})
        self.assertTrue(out['all_existing_physical_targets_hash_equal_at_observation_times'])
        self.assertFalse(out['compare_and_swap_authorized'])
        self.assertFalse(out['production_merge_authorized'])
        self.assertEqual(out['staging_bytes_written'], 0)
        self.assertFalse(out['market_files_written'])

    def test_prior_unobserved_and_current_observed_insufficient(self):
        out = S.compare(baseline(), observed(baseline()))
        self.assertEqual(out['difference_counts'],
                         {'ONE_TIMEPOINT_NOT_OBSERVED_CANNOT_COMPARE': 8})
        self.assertFalse(out['all_existing_physical_targets_hash_equal_at_observation_times'])

    def test_prior_observed_and_current_unobserved_insufficient(self):
        out = S.compare(observed(baseline()), baseline())
        self.assertEqual(out['difference_counts'],
                         {'ONE_TIMEPOINT_NOT_OBSERVED_CANNOT_COMPARE': 8})

    def test_absent_in_both_remains_blocked(self):
        r = missing(baseline())
        out = S.compare(r, r)
        self.assertEqual(out['difference_counts'],
                         {'ABSENT_AT_BOTH_TIMEPOINTS_STILL_BLOCKED': 8})
        self.assertFalse(out['all_existing_physical_targets_hash_equal_at_observation_times'])

    def test_file_appeared_is_drift_not_repair_proof(self):
        out = S.compare(missing(baseline()), observed(baseline()))
        self.assertEqual(out['difference_counts'], {'FILE_APPEARED_SINCE_PRIOR': 8})
        self.assertTrue(out['has_observed_file_drift'])
        self.assertFalse(out['original_producer_quarantines_cleared'])

    def test_file_disappeared_is_drift(self):
        out = S.compare(observed(baseline()), missing(baseline()))
        self.assertEqual(out['difference_counts'], {'FILE_DISAPPEARED_SINCE_PRIOR': 8})
        self.assertTrue(out['has_observed_file_drift'])

    def test_existing_sha_changed_is_drift(self):
        out = S.compare(observed(baseline(), sha='a' * 64),
                        observed(baseline(), sha='b' * 64))
        self.assertEqual(out['difference_counts'], {'FILE_BYTES_CHANGED_SINCE_PRIOR': 8})
        self.assertTrue(out['has_observed_file_drift'])
        self.assertFalse(out['compare_and_swap_authorized'])

    def test_single_file_sha_mutation_has_seven_unchanged(self):
        a = observed(baseline()); b = deepcopy(a)
        b['target_files'][0]['file_observation']['bytes_sha256'] = 'f' * 64
        seal(b)
        out = S.compare(a, b)
        self.assertEqual(out['difference_counts']['FILE_BYTES_CHANGED_SINCE_PRIOR'], 1)
        self.assertEqual(out['difference_counts']['OBSERVED_FILE_BYTES_SHA_UNCHANGED_BUT_NOT_LOCKED'], 7)
        self.assertTrue(out['has_observed_file_drift'])

    def test_current_plan_revision_requires_new_baseline_even_if_paths_same(self):
        old = baseline(); new = deepcopy(old)
        new['source_review_plan_sha256'] = 'f' * 64
        seal(new)
        with self.assertRaisesRegex(S.SnapshotError, 'NEW_BASELINE_REQUIRED'):
            S.compare(old, new)

    def test_current_backlog_revision_requires_new_baseline(self):
        old = baseline(); new = deepcopy(old)
        new['original_backlog_sha256'] = 'f' * 64
        seal(new)
        with self.assertRaisesRegex(S.SnapshotError, 'NEW_BASELINE_REQUIRED'):
            S.compare(old, new)

    def test_layout_year_mismatch_requires_new_baseline(self):
        old = TX.build_blueprint(R.build_review_plan(fixture(day='2019-02-15')),
                                 layout_year=2025)
        new = TX.build_blueprint(R.build_review_plan(fixture(day='2019-02-15')),
                                 layout_year=2026)
        with self.assertRaisesRegex(S.SnapshotError, 'NEW_BASELINE_REQUIRED'):
            S.compare(old, new)

    def test_deleted_target_rejected_even_with_resigned_report(self):
        old = baseline(); new = deepcopy(old)
        new['target_files'].pop()
        new['eight_period_target_file_count'] -= 1
        seal(new)
        with self.assertRaises(S.SnapshotError):S.compare(old, new)

    def test_forged_current_market_write_rejected_even_with_resigned_report(self):
        r = baseline(); r['market_parquet_or_h5_write_authorized'] = True
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError,'FORGED_MARKET_AUTHORITY'):
            S.validate_blueprint(r)

    def test_backup_or_restore_claim_rejected_even_if_sha_updated(self):
        for field in ('private_backup_materialized','rollback_tested',
                      'production_merge_authorized','producer_quarantine_cleared'):
            r = baseline(); r[field] = True; seal(r)
            with self.subTest(field=field), self.assertRaises(S.SnapshotError):
                S.validate_blueprint(r)

    def test_target_level_cas_or_restore_claim_rejected(self):
        for field in ('prechange_backup_created','restore_verified',
                      'compare_and_swap_authorized','write_authorized'):
            r = baseline(); r['target_files'][0][field] = True; seal(r)
            with self.subTest(field=field), self.assertRaisesRegex(
                    S.SnapshotError, 'FORGED_COMMIT_OR_BACKUP'):
                S.validate_blueprint(r)

    def test_diagnostic_sha_tamper_rejected_before_use(self):
        r = baseline(); r['target_files'][0]['relative_path'] = 'x/2026-11.parquet'
        with self.assertRaisesRegex(S.SnapshotError, 'BLUEPRINT_DIGEST_CHANGED'):
            S.validate_blueprint(r)

    def test_external_zero_sha_declared_present_rejected(self):
        r = observed(baseline()); r['target_files'][0]['file_observation']['bytes_sha256'] = None
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError, 'OBSERVED_FILE_SHA_OR_SIZE_INVALID'):
            S.validate_blueprint(r)

    def test_forged_unobserved_physical_sha_rejected(self):
        r = baseline(); r['target_files'][0]['file_observation']['bytes_sha256'] = 'a' * 64
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError, 'UNOBSERVED_OR_MISSING_SHA_FORGED'):
            S.validate_blueprint(r)

    def test_filename_path_traversal_rejected_with_recomputed_sha(self):
        r = baseline(); r['target_files'][0]['relative_path'] = '../1min/2026-11.parquet'
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError, 'TARGET_PATH_INVALID'):
            S.validate_blueprint(r)

    def test_physical_scope_and_count_forgery_rejected(self):
        r = baseline(); r['physical_target_files_checked'] = 8; seal(r)
        with self.assertRaisesRegex(S.SnapshotError, 'PHYSICAL_CHECK_SCOPE_INVALID'):
            S.validate_blueprint(r)

    def test_duplicate_request_id_or_wrong_eight_period_count_rejected(self):
        r = baseline(); r['target_files'][0]['affected_review_request_ids'] = ['f' * 64]
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError, 'EIGHT_PERIOD_CONSERVATION_FAILED'):
            S.validate_blueprint(r)

    def test_same_request_must_cover_all_distinct_eight_periods(self):
        report = baseline()
        # Replace a 5min target by another 1min file in an adjacent month.
        target = next(t for t in report['target_files'] if t['relative_path'].startswith('5min/'))
        target['relative_path'] = '1min/2026-10.parquet'
        report['target_files'].sort(key=lambda t:t['relative_path'])
        seal(report)
        with self.assertRaisesRegex(S.SnapshotError, 'EIGHT_PERIOD_CONSERVATION_FAILED'):
            S.validate_blueprint(report)

    def test_source_sha_and_layout_identities_are_preserved(self):
        r = observed(baseline()); out = S.compare(r, r)
        self.assertEqual(out['source_review_plan_sha256'], r['source_review_plan_sha256'])
        self.assertEqual(out['current_blueprint_sha256'], r['blueprint_sha256'])
        self.assertEqual(out['comparison_sha256'], R.digest({k:v for k,v in out.items()
                                                             if k!='comparison_sha256'}))

    def test_prior_file_actual_sha_and_internal_digest_checked(self):
        with TemporaryDirectory() as td:
            root = Path(td); p = root / 'prior.json'
            original = observed(baseline()); p.write_bytes(R.canonical(original))
            expected = sha256(p.read_bytes()).hexdigest()
            self.assertEqual(S.read_prior(root, 'prior.json', expected), original)
            with self.assertRaisesRegex(S.SnapshotError, 'SHA_OR_SIZE_MISMATCH'):
                S.read_prior(root, 'prior.json', 'f' * 64)
            p.write_bytes(b'corrupted')
            with self.assertRaises(S.SnapshotError):S.read_prior(root, 'prior.json', expected)

    def test_oversize_prior_refused_before_large_hash(self):
        with TemporaryDirectory() as td:
            root=Path(td); file=root/'oversize.json'
            file.write_bytes(b' ' * (S.MAX_PRIOR_BYTES + 1))
            with self.assertRaisesRegex(S.SnapshotError,'SHA_OR_SIZE_MISMATCH'):
                S.read_prior(root,'oversize.json','a'*64)

    def test_prior_file_duplicate_json_key_refused(self):
        with TemporaryDirectory() as td:
            root = Path(td); p = root / 'prior.json'
            p.write_bytes(b'{"format":"fake",' + R.canonical(baseline())[1:])
            with self.assertRaisesRegex(S.SnapshotError,'DUPLICATE_SNAPSHOT_JSON_KEY'):
                S.read_prior(root, 'prior.json', sha256(p.read_bytes()).hexdigest())

    def test_prior_symlink_and_parent_traversal_rejected(self):
        with TemporaryDirectory() as td:
            root=Path(td);p=root/'prior.json';p.write_bytes(R.canonical(baseline()))
            expected=sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):S.read_prior(root,'../prior.json',expected)
            link=root/'linked.json'
            try:link.symlink_to(p)
            except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
            with self.assertRaises(ValueError):S.read_prior(root,'linked.json',expected)

    def test_real_temporary_target_byte_observation_end_to_end_no_writes(self):
        with TemporaryDirectory() as td:
            root=Path(td);base=root/'AllCycleAStockData'
            for period in TX.PERIODS:(base/period).mkdir(parents=True)
            f=base/'1min'/'2026-11.parquet';f.write_bytes(b'fake temporary source')
            before=(f.read_bytes(), f.stat().st_mtime_ns)
            # Temp layout injected; actual file-byte SHA reader remains unchanged.
            with mock.patch.dict(sys.modules,{'local_layout':types.SimpleNamespace(
                    storage_root=lambda source, require_all=True: base)}):
                current=TX.build_blueprint(R.build_review_plan(fixture()),
                                           layout_year=2026,target_root=root)
            original=missing(baseline())
            out=S.compare(original,current)
            self.assertEqual(out['difference_counts']['FILE_APPEARED_SINCE_PRIOR'],1)
            self.assertEqual(out['difference_counts']['ABSENT_AT_BOTH_TIMEPOINTS_STILL_BLOCKED'],7)
            self.assertEqual(before,(f.read_bytes(), f.stat().st_mtime_ns))
            self.assertFalse(out['market_files_written'])

    def test_cli_without_prior_never_implies_stable_files(self):
        source=StringIO()
        with mock.patch.object(TX, 'inspect', return_value=baseline()):
            with contextlib.redirect_stdout(source):
                result=S.main(['--module-root','/fake','--start-day','2026-11-25',
                               '--end-day','2026-11-25','--layout-year','2026','--summary-only'])
        self.assertEqual(result,0)
        doc=json.loads(source.getvalue())
        self.assertEqual(doc['status'], 'NO_PRIOR_BLUEPRINT_SUPPLIED_COMPARISON_NOT_PERFORMED')
        self.assertNotIn('target_files',doc)
        self.assertFalse(doc['physical_source_lock_held'])

    def test_invalid_cli_prior_triple_fails_closed_and_no_path_leak(self):
        output=StringIO()
        with contextlib.redirect_stdout(output):
            rc=S.main(['--module-root','/private/work','--start-day','2026-11-25',
                       '--end-day','2026-11-25','--layout-year','2026',
                       '--prior-relative','snapshot.json'])
        self.assertEqual(rc,3)
        self.assertNotIn('/private/work',output.getvalue())

    def test_source_contains_no_market_writer_or_history_downloader(self):
        import inspect
        src=inspect.getsource(S)
        for forbidden in ('write_table(', 'write_bytes(', 'download_history_data(',
                          'os.replace(', 'shutil.copyfile(', 'CreateFile('):
            self.assertNotIn(forbidden,src)


    def test_resigned_one_request_spread_across_month_shards_is_rejected(self):
        report = baseline()
        target = next(x for x in report['target_files']
                      if x['relative_path'].startswith('1min/'))
        target['relative_path'] = '1min/2026-10.parquet'
        report['target_files'].sort(key=lambda x: x['relative_path'])
        seal(report)
        with self.assertRaisesRegex(S.SnapshotError, 'CROSS_PERIOD_SHARD_MISMATCH'):
            S.validate_blueprint(report)

    def test_resigned_one_request_spread_across_year_shards_is_rejected(self):
        report = TX.build_blueprint(
            R.build_review_plan(fixture(day='2019-02-15')), layout_year=2026)
        target = next(x for x in report['target_files']
                      if x['relative_path'].startswith('day/'))
        target['relative_path'] = 'day/2018.parquet'
        report['target_files'].sort(key=lambda x: x['relative_path'])
        seal(report)
        with self.assertRaisesRegex(S.SnapshotError, 'CROSS_PERIOD_SHARD_MISMATCH'):
            S.validate_blueprint(report)

    def test_different_requests_may_legitimately_use_different_shards(self):
        report = baseline()
        others = deepcopy(report['target_files'])
        for target in others:
            target['relative_path'] = target['relative_path'].replace(
                '/2026-11.parquet', '/2026-10.parquet')
            target['affected_review_request_ids'] = ['b' * 64]
        report['target_files'].extend(others)
        report['target_files'].sort(key=lambda x: x['relative_path'])
        report['recovery_review_request_count'] = 2
        report['eight_period_target_file_count'] = 16
        seal(report)
        self.assertEqual(len(S.validate_blueprint(report)), 16)

    def test_same_digest_but_different_declared_byte_sizes_fails_closed(self):
        prior = observed(baseline(), sha='a' * 64, nbytes=400)
        current = observed(baseline(), sha='a' * 64, nbytes=401)
        with self.assertRaisesRegex(S.SnapshotError,
                                    'IDENTICAL_SHA_DIFFERENT_FILE_SIZE'):
            S.compare(prior, current)

    def test_sha_case_only_change_does_not_claim_physical_drift(self):
        prior = observed(baseline(), sha='a' * 64)
        current = observed(baseline(), sha='A' * 64)
        out = S.compare(prior, current)
        self.assertEqual(out['difference_counts'],
                         {'OBSERVED_FILE_BYTES_SHA_UNCHANGED_BUT_NOT_LOCKED': 8})
        self.assertFalse(out['has_observed_file_drift'])
        self.assertFalse(out['compare_and_swap_authorized'])

    def test_no_physical_observation_has_zero_sha_pairs_not_a_pass(self):
        out = S.compare(baseline(), baseline())
        self.assertEqual(out['physical_sha_pairs_compared'], 0)
        self.assertEqual(out['not_observed_at_one_or_both_timepoints'], 8)
        self.assertEqual(out['absent_at_one_or_both_timepoints'], 0)
        self.assertFalse(out['full_physical_sha_pair_coverage'])

    def test_appeared_files_do_not_count_as_two_physical_observations(self):
        out = S.compare(missing(baseline()), observed(baseline()))
        self.assertEqual(out['physical_sha_pairs_compared'], 0)
        self.assertEqual(out['absent_at_one_or_both_timepoints'], 8)
        self.assertFalse(out['full_physical_sha_pair_coverage'])
        self.assertTrue(out['has_observed_file_drift'])

    def test_mixed_absent_and_real_sha_pairs_are_counted_separately(self):
        old = missing(baseline())
        new = observed(baseline(), sha='c' * 64)
        old['target_files'][0]['file_observation'] = deepcopy(
            new['target_files'][0]['file_observation'])
        seal(old)
        out = S.compare(old, new)
        self.assertEqual(out['physical_sha_pairs_compared'], 1)
        self.assertEqual(out['absent_at_one_or_both_timepoints'], 7)
        self.assertEqual(out['not_observed_at_one_or_both_timepoints'], 0)
        self.assertFalse(out['full_physical_sha_pair_coverage'])

    def test_full_sha_pair_coverage_can_still_contain_drift_no_commit(self):
        old = observed(baseline(), sha='a' * 64)
        new = observed(baseline(), sha='b' * 64)
        out = S.compare(old, new)
        self.assertTrue(out['full_physical_sha_pair_coverage'])
        self.assertEqual(out['physical_sha_pairs_compared'], 8)
        self.assertTrue(out['has_observed_file_drift'])
        self.assertFalse(out['physical_source_lock_held'])
        self.assertFalse(out['backup_materialized_or_restoration_tested'])
        self.assertFalse(out['market_files_written'])


    def test_unknown_forged_top_level_authority_rejected_after_reseal(self):
        r = baseline()
        r['fully_approved_for_market_commit'] = True
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError,
                                    'BLUEPRINT_UNKNOWN_OR_MISSING_FIELDS'):
            S.validate_blueprint(r)

    def test_unknown_harmless_seeming_field_also_rejected_after_reseal(self):
        r = baseline()
        r['new_optional_producer_snapshot'] = None
        seal(r)
        with self.assertRaisesRegex(S.SnapshotError,
                                    'BLUEPRINT_UNKNOWN_OR_MISSING_FIELDS'):
            S.validate_blueprint(r)

    def test_boolean_false_is_not_valid_integer_zero_evidence(self):
        for name in ('qmt_history_download_calls',
                     'staging_bytes_written', 'production_bytes_written'):
            r = baseline()
            r[name] = False
            seal(r)
            with self.subTest(field=name), self.assertRaisesRegex(
                    S.SnapshotError, 'UNEXPECTED_MUTATION'):
                S.validate_blueprint(r)

if __name__ == '__main__':unittest.main()
