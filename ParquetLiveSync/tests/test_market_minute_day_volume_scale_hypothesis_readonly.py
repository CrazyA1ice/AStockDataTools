"""Pure read-only ratio hypothesis tests with P3.9-style validated response fixtures."""
from __future__ import annotations

from copy import deepcopy
import contextlib
from io import StringIO
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_minute_day_volume_scale_hypothesis_readonly as H

FIELDS=H.FIELDS

def paired(day, *, factor=100, amount_eps=0.0):
    daily={'open':10.,'high':11.,'low':9.,'close':10.5,
           'volume':10000.,'amount':1000000.}
    minute=dict(daily)
    minute['volume']/=factor
    minute['amount']+=amount_eps
    vals={}
    for name in FIELDS:
        m,d=minute[name],daily[name]
        vals[name]={'minute_raw':m,'declared_day':d,
                    'raw_delta':m-d,'raw_relative_delta':(m-d)/max(abs(d),1e-12)}
    return {
        'day':day,'minute_rows':241,'minute_grid_status':'EXACT_241_WITH_0930',
        'declared_day_overlay_state':H.PAIRED,
        'day_overlay_parquet_bytes_sha256':'c'*64,
        'day_overlay_receipt_bytes_sha256':'d'*64,
        'raw_six_field_difference_without_calibration':vals,
        'provider_identity_authenticated':False,
        'six_field_quality_certified':False,
        'production_repair_authorized':False,
    }

def empty(day):
    return {
        'day':day,'minute_rows':0,
        'minute_grid_status':'NO_ROWS_CALENDAR_DAY_NOT_PROVED_TRADING',
        'declared_day_overlay_state':'NO_MINUTE_ROWS_CALENDAR_DAY_NOT_TRADING_CERTIFIED',
        'raw_six_field_difference_without_calibration':None,
        'provider_identity_authenticated':False,
        'six_field_quality_certified':False,
        'production_repair_authorized':False,
    }

def valid(days=None):
    if days is None:
        days=[paired('2026-11-10',amount_eps=.02),paired('2026-11-11',factor=100.0001),
              empty('2026-11-12')]
    counts={}
    for d in days:
        x=d['declared_day_overlay_state'];counts[x]=counts.get(x,0)+1
    return {
        'format':H.PAIR.FORMAT,'status':H.PAIR.STATUS,
        'symbol':'300119.SZ','window':['2026-11-10','2026-11-12'],
        'minute_physical_file_sha256':'a'*64,'raw_diagnostic_scope_sha256':'b'*64,
        'calendar_days':len(days),'minute_rows_checked':sum(x['minute_rows'] for x in days),
        'day_overlay_status_counts':counts,'days':days,
        'data_source_independence_or_provider_identity_certified':False,
        'official_exchange_calendar_and_stock_universe_certified':False,
        'qmt_native_provider_authenticated':False,
        'paid_minutes_units_or_timestamp_calibrated':False,
        'six_field_quality_passed':False,'eight_period_aggregation_reconciled':False,
        'market_candidate_validated':False,'producer_quarantine_closed':False,
        'backup_materialized':False,'physical_source_lock_held':False,
        'production_merge_authorized':False,'market_files_written':False,
        'qmt_cache_modified':False,'qmt_history_download_calls':0,
    }

class HypothesisTests(unittest.TestCase):
    def test_two_actual_pairs_select_observed_factor_100_not_approved(self):
        r=H.summarize(valid())
        self.assertEqual(r['physical_day_comparisons'],2)
        self.assertEqual(r['lowest_median_error_candidate_not_approved'],100)
        self.assertAlmostEqual(r['volume_minute_over_day_ratio']['median'],.01,delta=1e-7)
        self.assertFalse(r['candidate_factor_is_approved_calibration'])
        self.assertFalse(r['volume_factor_applied_to_data'])
        self.assertFalse(r['six_field_quality_passed'])
        self.assertFalse(r['production_merge_authorized'])

    def test_100_candidate_diagnostic_does_not_alter_raw_amount(self):
        x=valid();original=deepcopy(x)
        r=H.summarize(x)
        self.assertEqual(x,original)
        self.assertEqual(r['amount_raw_abs_relative_error']['count'],2)
        self.assertGreater(r['amount_raw_abs_relative_error']['maximum'],0)
        self.assertLess(r['volume_candidate_abs_relative_error']['100']['maximum'],2e-6)

    def test_implied_factor_10_picked_as_descriptive_only(self):
        r=H.summarize(valid([paired('2026-11-10',factor=10)]))
        self.assertEqual(r['lowest_median_error_candidate_not_approved'],10)
        self.assertFalse(r['purchased_feed_units_or_timestamp_calibrated'])

    def test_exact_1_candidate_picked_not_certified(self):
        r=H.summarize(valid([paired('2026-11-10',factor=1)]))
        self.assertEqual(r['lowest_median_error_candidate_not_approved'],1)
        self.assertFalse(r['independent_provider_identity_verified'])

    def test_outlier_shown_in_maximum_not_hidden_by_median(self):
        days=[paired('2026-11-10'),paired('2026-11-11'),paired('2026-11-12',factor=10)]
        r=H.summarize(valid(days))
        self.assertEqual(r['lowest_median_error_candidate_not_approved'],100)
        self.assertGreater(r['volume_candidate_abs_relative_error']['100']['maximum'],8)
        self.assertEqual(r['volume_candidate_abs_relative_error']['100']['count'],3)

    def test_raw_price_difference_is_not_hidden(self):
        x=valid([paired('2026-11-10')])
        row=x['days'][0]['raw_six_field_difference_without_calibration']['close']
        row['minute_raw']=11.
        row['raw_delta']=.5
        row['raw_relative_delta']=.5/10.5
        result=H.summarize(x)
        self.assertGreater(result['price_raw_abs_relative_error']['close']['maximum'],.04)
        self.assertFalse(result['six_field_quality_passed'])

    def test_fractional_amount_error_not_claimed_rounding_pass(self):
        x=valid([paired('2026-11-10',amount_eps=0.05)])
        result=H.summarize(x)
        self.assertGreater(result['six_fields_raw_abs_relative_error']['amount']['median'],0)
        self.assertFalse(result['purchased_feed_units_or_timestamp_calibrated'])

    def test_unpaired_days_count_but_not_in_volume_statistics(self):
        r=H.summarize(valid())
        self.assertEqual(r['volume_minute_over_day_ratio']['count'],2)
        self.assertEqual(r['nonpaired_status_counts'],
                         {'NO_MINUTE_ROWS_CALENDAR_DAY_NOT_TRADING_CERTIFIED':1})
        self.assertEqual(r['minute_rows_checked'],482)

    def test_bad_sha_scope_fails_closed(self):
        x=valid();x['raw_diagnostic_scope_sha256']='not a sha'
        with self.assertRaisesRegex(H.HypothesisError,'IDENTITY_INVALID'):
            H.summarize(x)

    def test_unauthorized_upstream_claim_not_accepted(self):
        for field in ('six_field_quality_passed','market_files_written',
                      'producer_quarantine_closed',
                      'paid_minutes_units_or_timestamp_calibrated'):
            x=valid();x[field]=True
            with self.subTest(field=field),self.assertRaisesRegex(H.HypothesisError,'UNAUTHORIZED'):
                H.summarize(x)

    def test_boolean_qmt_history_download_claim_rejected(self):
        x=valid();x['qmt_history_download_calls']=False
        with self.assertRaisesRegex(H.HypothesisError,'DOWNLOAD_CLAIM'):
            H.summarize(x)

    def test_reject_forged_paired_240_or_239_source_day(self):
        for n in (239,240):
            x=valid();x['days'][0]['minute_rows']=n
            x['minute_rows_checked']-=241-n
            with self.subTest(count=n),self.assertRaisesRegex(H.HypothesisError,'PAIRED_241'):
                H.summarize(x)

    def test_unpaired_missing_day_cannot_supply_forged_raw_prices(self):
        x=valid();x['days'][2]['raw_six_field_difference_without_calibration']={}
        with self.assertRaisesRegex(H.HypothesisError,'UNPAIRED_DAY_HAS_FORGED'):
            H.summarize(x)

    def test_unrecognized_six_field_payload_fails(self):
        x=valid();x['days'][0]['raw_six_field_difference_without_calibration']['other']={'x':2}
        with self.assertRaisesRegex(H.HypothesisError,'PAIRED_241'):
            H.summarize(x)

    def test_boolean_ohlc_value_rejected(self):
        x=valid();x['days'][0]['raw_six_field_difference_without_calibration']['open']['minute_raw']=True
        with self.assertRaisesRegex(H.HypothesisError,'NOT_NUMBER'):
            H.summarize(x)

    def test_nonfinite_qmt_volume_rejected(self):
        x=valid();x['days'][0]['raw_six_field_difference_without_calibration']['volume']['minute_raw']=float('nan')
        with self.assertRaisesRegex(H.HypothesisError,'NONFINITE'):
            H.summarize(x)

    def test_zero_volume_reference_is_skipped_but_all_zero_rejected(self):
        x=valid([paired('2026-11-10')])
        f=x['days'][0]['raw_six_field_difference_without_calibration']['volume']
        f.update(minute_raw=0.,declared_day=0.,raw_delta=0.,raw_relative_delta=0.)
        with self.assertRaisesRegex(H.HypothesisError,'NO_POSITIVE_VOLUME'):
            H.summarize(x)

    def test_raw_delta_must_reconcile_to_raw_values(self):
        x=valid();x['days'][0]['raw_six_field_difference_without_calibration']['amount']['raw_delta']=10.0
        with self.assertRaisesRegex(H.HypothesisError,'NOT_CONSERVED'):
            H.summarize(x)

    def test_repeated_day_rejected(self):
        x=valid();x['days'][1]['day']=x['days'][0]['day']
        with self.assertRaisesRegex(H.HypothesisError,'WINDOW_DUPLICATE'):
            H.summarize(x)

    def test_no_paired_day_rejected(self):
        with self.assertRaisesRegex(H.HypothesisError,'NO_COMPARABLE'):
            H.summarize(valid([empty('2026-11-10')]))

    def test_deterministic_scope_digest_for_identical_evidence(self):
        x=valid()
        self.assertEqual(H.summarize(x),H.summarize(deepcopy(x)))
        self.assertEqual(len(H.summarize(x)['descriptive_hypothesis_scope_sha256']),64)

    def test_reject_day_status_count_tampering(self):
        x=valid();x['day_overlay_status_counts'][H.PAIRED]=3
        with self.assertRaisesRegex(H.HypothesisError,'COUNTS_DISAGREE'):
            H.summarize(x)

    def test_mocked_full_upstream_call_uses_exact_user_supplied_args(self):
        x=valid()
        with mock.patch.object(H.PAIR,'inspect',return_value=x) as get:
            r=H.inspect('private-root','minute.jsonl','a'*64,
                        '300119.SZ','2026-11-10','2026-11-12','day-module')
        get.assert_called_once_with('private-root','minute.jsonl','a'*64,
                                    '300119.SZ','2026-11-10','2026-11-12','day-module')
        self.assertEqual(r['physical_day_comparisons'],2)

    def test_cli_fails_closed_without_private_path_leak(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            rc=H.main(['--minute-evidence-root','/private/private',
                       '--minute-file-relative','file.jsonl',
                       '--expected-minute-sha256','a'*64,
                       '--symbol','300119.SZ','--start-day','2026-11-10',
                       '--end-day','2026-11-12','--module-root','/private/day'])
        self.assertEqual(rc,3)
        self.assertNotIn('/private',out.getvalue())

    def test_module_contains_no_writer_or_qmt_download_api(self):
        import inspect
        s=inspect.getsource(H)
        for prohibited in ('get_market_data_ex(', 'download_history_data(',
                           'write_bytes(', 'write_table(', 'os.replace(', 'mkdir('):
            self.assertNotIn(prohibited,s)


if __name__ == '__main__':
    unittest.main()
