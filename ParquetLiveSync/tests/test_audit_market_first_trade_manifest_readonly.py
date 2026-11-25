"""Deterministic, fail-closed, non-admitting original two-stock evidence tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_audit_market_opening_auction_readonly import rows, fake_update
from audit_market_opening_auction_readonly import replay_one
import audit_market_first_trade_manifest_readonly as M


def real_like_replay(symbol, expected_open, quote_open, first_trade_index):
    native = rows(False)
    for i, bar in enumerate(native):
        bar['open'] = quote_open
        bar['high'] = 9.68 if symbol == 'SZ300462' else 8.31
        bar['low'] = 9.26 if symbol == 'SZ300462' else 7.62
        bar['close'] = 9.27 if symbol == 'SZ300462' else 7.95
        if i < first_trade_index:
            bar['volume'] = 0.
            bar['amount'] = 0.
    native[first_trade_index]['open'] = expected_open
    days = len(native)-first_trade_index
    official = dict(open=expected_open, high=native[0]['high'],
                    low=native[0]['low'], close=native[-1]['close'],
                    volume=float(2*days), amount=float(20*days))
    code = symbol[2:] + '.' + symbol[:2]
    r = replay_one(fake_update(), code, native, official, {}, __import__('datetime').date(2026,11,25))
    return r


def sample_report():
    return {
        'status': 'TWO_STOCK_OPENING_PROVENANCE_READ_ONLY_NOT_REPAIR',
        'original_run_sha256': M.RUN_SHA,
        'official_day_overlay_parquet_sha256': M.OFFICIAL_SHA,
        'official_day_overlay_receipt_sha256': M.OFFICIAL_RECEIPT_SHA,
        'qmt_historical_download_called': False,
        'project_data_modified': False,
        'data_quality_cleared': False,
        'stocks': [real_like_replay('SH605336',7.62,7.69,2),
                   real_like_replay('SZ300462',9.4,9.59,3)],
    }


class CandidateManifestTests(unittest.TestCase):
    def setUp(self):
        self.source = sample_report()

    def test_full_replay_yields_two_review_only_candidates(self):
        obj = M.certify_diagnostic_only(self.source)
        self.assertEqual(obj['candidate_count'], 2)
        self.assertEqual(obj['status'], 'FIRST_TRADE_OPENING_CANDIDATES_VERIFIED_DIAGNOSTIC_ONLY')
        self.assertEqual([c['first_genuine_trade_label'] for c in obj['candidates']], ['09:32','09:33'])
        self.assertEqual(obj['source']['scheduled_run_sha256'],M.RUN_SHA)
        self.assertTrue(obj['original_nine_quarantines_retained'])
        self.assertFalse(obj['production_merge_authorized'])
        self.assertFalse(obj['project_market_files_modified'])
        self.assertFalse(obj['data_quality_cleared'])
        self.assertTrue(all(c['admission_authorized'] is False for c in obj['candidates']))
        self.assertIn('NOT_RAW_241',obj['diagnostic_digest_scope'])

    def test_manifest_digest_matches_canonical_without_self_reference(self):
        obj=M.certify_diagnostic_only(self.source)
        digest=obj.pop('manifest_sha256')
        self.assertEqual(M.digest(obj),digest)

    def test_deterministic_across_reordering_of_two_stock_results(self):
        x=M.certify_diagnostic_only(self.source)
        swapped=deepcopy(self.source)
        swapped['stocks'].reverse()
        y=M.certify_diagnostic_only(swapped)
        self.assertEqual(x['candidates'],y['candidates'])
        self.assertNotEqual(x['diagnostic_snapshot_sha256'],y['diagnostic_snapshot_sha256'])
        self.assertNotEqual(x['manifest_sha256'],y['manifest_sha256'])
        self.assertEqual(x,M.certify_diagnostic_only(self.source))

    def test_changed_original_run_sha_rejected(self):
        self.source['original_run_sha256']='f'*64
        with self.assertRaisesRegex(M.ManifestError,'ORIGINAL_RUN_SHA_CHANGED'):
            M.certify_diagnostic_only(self.source)

    def test_official_parquet_and_receipt_pins_rejected(self):
        for field in ('official_day_overlay_parquet_sha256','official_day_overlay_receipt_sha256'):
            with self.subTest(field=field):
                source=deepcopy(self.source)
                source[field]='f'*64
                with self.assertRaises(M.ManifestError):
                    M.certify_diagnostic_only(source)

    def test_source_written_or_downloaded_or_quality_cleared_rejected(self):
        for field in ('project_data_modified','qmt_historical_download_called','data_quality_cleared'):
            with self.subTest(field=field):
                source=deepcopy(self.source)
                source[field]=True
                with self.assertRaisesRegex(M.ManifestError,'SIDE_EFFECT'):
                    M.certify_diagnostic_only(source)

    def test_only_exact_two_distinct_symbols_allowed(self):
        for stocks in (self.source['stocks'][:1],self.source['stocks'][:1]*2,
                       [dict(self.source['stocks'][0],symbol='SH000001'),self.source['stocks'][1]]):
            with self.subTest(n=len(stocks)):
                src=deepcopy(self.source)
                src['stocks']=stocks
                with self.assertRaises(M.ManifestError):
                    M.certify_diagnostic_only(src)

    def test_opening_time_drift_rejected(self):
        self.source['stocks'][0]['first_positive_trade_diagnostic']['first_positive_label']='09:33'
        with self.assertRaisesRegex(M.ManifestError,'FIRST_TRADE_CLOCK_CHANGED'):
            M.certify_diagnostic_only(self.source)

    def test_strict_open_match_must_reproduce(self):
        self.source['stocks'][0]['first_positive_trade_diagnostic']['strict_official_open_match']=False
        with self.assertRaisesRegex(M.ManifestError,'NOT_STRICTLY_COMPATIBLE'):
            M.certify_diagnostic_only(self.source)

    def test_original_failed_validation_cannot_be_silently_cleared(self):
        self.source['stocks'][1]['full_original_validation_error']=None
        with self.assertRaisesRegex(M.ManifestError,'ORIGINAL_QUARANTINE_NO_LONGER_REPRODUCES'):
            M.certify_diagnostic_only(self.source)

    def test_reported_six_fields_recomputed_and_not_taken_on_trust(self):
        self.source['stocks'][0]['field_comparisons']['high']['within_existing_tolerance']=False
        with self.assertRaisesRegex(M.ManifestError,'REPORTED_COMPARISON_INCONSISTENT'):
            M.certify_diagnostic_only(self.source)

    def test_downstream_close_mismatch_does_not_qualify(self):
        r=self.source['stocks'][0]
        r['folded_day_ohlcva']['close']=9.
        r['field_comparisons']['close']['within_existing_tolerance']=False
        r['field_comparisons']['close']['absolute_difference']=9.-r['official_day_ohlcva']['close']
        with self.assertRaisesRegex(M.ManifestError,'UNEXPECTED_EXTRA_FIELD_MISMATCH'):
            M.certify_diagnostic_only(self.source)

    def test_nonfinite_values_fail_without_output_or_source_write(self):
        self.source['stocks'][0]['folded_day_ohlcva']['amount']=math.inf
        with self.assertRaisesRegex(M.ManifestError,'NONFINITE_NUMERIC_FIELD'):
            M.certify_diagnostic_only(self.source)

    def test_0930_real_auction_not_treated_as_zero_prefix(self):
        self.source['stocks'][0]['auction_kind']='REAL_AUCTION_FOLDED_TO_0931'
        with self.assertRaisesRegex(M.ManifestError,'REAL_0930_AUCTION'):
            M.certify_diagnostic_only(self.source)

    def test_real_0930_nonzero_pair_not_accepted_as_zero_placeholder(self):
        self.source['stocks'][0]['raw_0930_volume']=3.
        with self.assertRaisesRegex(M.ManifestError,'0930_NOT_ZERO_PLACEHOLDER'):
            M.certify_diagnostic_only(self.source)

    def test_missing_optin_never_calls_runner(self):
        fn=Mock(return_value=self.source)
        out=StringIO()
        with redirect_stdout(out):
            code=M.main(['--module-root','C:/synthetic'],runner=fn)
        self.assertEqual(code,3)
        fn.assert_not_called()
        self.assertIn('REVIEW_REQUIRED',out.getvalue())

    def test_main_one_original_auditor_call_and_no_file_write(self):
        runner=Mock(return_value=self.source)
        out=StringIO()
        with redirect_stdout(out):
            code=M.main(['--module-root','C:/synthetic','--confirm-two-stock-cache-query'],runner=runner)
        self.assertEqual(code,0)
        runner.assert_called_once_with(Path('C:/synthetic'),confirm=True)
        result=json.loads(out.getvalue())
        self.assertEqual(result['candidate_count'],2)
        self.assertFalse(result['production_merge_authorized'])

    def test_incomplete_report_fails_closed_without_traceback(self):
        report={'status':'TWO_STOCK_OPENING_PROVENANCE_READ_ONLY_NOT_REPAIR'}
        out=StringIO()
        with redirect_stdout(out):
            code=M.main(['--module-root','C:/synthetic','--confirm-two-stock-cache-query'],
                        runner=Mock(return_value=report))
        self.assertEqual(code,3)
        self.assertIn('REVIEW_REQUIRED',out.getvalue())


if __name__=='__main__':unittest.main()
