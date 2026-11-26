"""Existing JSONL physical-byte and synthetic overlay-receipt gate tests."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_native_minute_day_overlay_window_readonly as X
import market_native_minute_jsonl_readonly as M
import market_live_day_overlay_audit as OVERLAY
import market_official_day_content_readonly as DAY

CN = timezone(timedelta(hours=8))


def stock_day(day='2026-11-10', symbol='300119.SZ', labels=None):
    if labels is None:
        labels = M.GRID
    return [
        {'datetime_cn': datetime.fromisoformat(day).replace(hour=h, minute=m,
                                                             tzinfo=CN).isoformat(),
         'symbol': symbol, 'open': 10., 'high': 11., 'low': 9.,
         'close': 10.5, 'volume': 100., 'amount': 1010.}
        for h, m in sorted(labels)
    ]


def source(root, rows=None):
    path = Path(root) / 'probe.jsonl'
    if rows is None:
        rows = stock_day()
    blob = b''.join((json.dumps(r, sort_keys=True) + '\n').encode('utf-8')
                    for r in rows)
    path.write_bytes(blob)
    return sha256(blob).hexdigest()


def args(root, digest, **change):
    result = dict(minute_root=root, minute_relative='probe.jsonl',
                  minute_sha256=digest, symbol='300119.SZ',
                  start_day='2026-11-10', end_day='2026-11-12',
                  module_root=root)
    result.update(change)
    return result


def overlay(day='2026-11-10', symbol='SZ300119', **updates):
    o = {
        'status': OVERLAY.STATUS, 'day': day, 'symbol': symbol,
        'live_state_bytes_sha256': 'a'*64,
        'day_overlay_receipt_bytes_sha256': 'b'*64,
        'day_overlay_parquet_bytes_sha256': 'c'*64,
        'day_content_fields_and_target_checked': True,
        'target_ohlcva': {
            'open': 10., 'high': 11., 'low': 9., 'close': 10.5,
            'volume': 24100., 'amount': 243410.,
        },
        'whole_exchange_stock_day_universe_certified': False,
        'provider_identity_authenticated': False,
        'tdx_raw_zip_bytes_verified': False,
        'tdx_raw_zip_file_bytes_sha256_if_checked': None,
        'qmt_native_1min_verified': False,
        'market_candidate_validated': False,
        'original_nine_quarantines_cleared': False,
        'market_data_write_authorized': False,
        'market_files_written': False,
        'qmt_history_download_calls': 0,
    }
    o.update(updates)
    return o


class OverlayWindowTests(unittest.TestCase):
    def test_one_verified_241_day_and_two_absent_calendar_days(self):
        with TemporaryDirectory() as root:
            digest = source(root)
            r = X.inspect(**args(root,digest),
                          overlay_reader=lambda directory,day,symbol: overlay(day,symbol))
            self.assertEqual(r['calendar_days'],3)
            self.assertEqual(r['minute_rows_checked'],241)
            self.assertEqual(r['day_overlay_status_counts'],
                             {'LOCAL_DAY_OVERLAY_CONTENT_SHA_VERIFIED_RAW_DIAGNOSTICS':1,
                              'NO_MINUTE_ROWS_CALENDAR_DAY_NOT_TRADING_CERTIFIED':2})
            self.assertEqual(r['days'][0]['raw_six_field_difference_without_calibration']['volume']['raw_delta'],0.)
            self.assertFalse(r['six_field_quality_passed'])
            self.assertFalse(r['official_exchange_calendar_and_stock_universe_certified'])
            self.assertFalse(r['production_merge_authorized'])

    def test_physical_real_file_is_unchanged(self):
        with TemporaryDirectory() as root:
            digest = source(root)
            p = Path(root)/'probe.jsonl'
            before = (p.read_bytes(),p.stat().st_mtime_ns)
            X.inspect(**args(root,digest),overlay_reader=lambda a,b,c:overlay(b,c))
            self.assertEqual((p.read_bytes(),p.stat().st_mtime_ns),before)

    def test_240_missing_opening_is_never_compared(self):
        with TemporaryDirectory() as root:
            digest=source(root,stock_day(labels=M.GRID_240))
            with mock.patch.object(X.OVERLAY,'inspect',side_effect=AssertionError('should not inspect DAY')):
                r=X.inspect(**args(root,digest))
            self.assertEqual(r['days'][0]['declared_day_overlay_state'],'MINUTE_GRID_INCOMPLETE_NOT_COMPARED')
            self.assertFalse(r['qmt_native_provider_authenticated'])

    def test_239_partial_minute_is_never_compared(self):
        with TemporaryDirectory() as root:
            digest=source(root,stock_day(labels=M.GRID-{(9,30),(10,0)}))
            with mock.patch.object(X.OVERLAY,'inspect',side_effect=AssertionError('should not inspect DAY')):
                r=X.inspect(**args(root,digest))
            self.assertEqual(r['days'][0]['minute_rows'],239)
            self.assertIsNone(r['days'][0]['raw_six_field_difference_without_calibration'])

    def test_first_calendar_day_absent_later_day_241_compared(self):
        with TemporaryDirectory() as root:
            digest=source(root,stock_day('2026-11-12'))
            r=X.inspect(**args(root,digest),overlay_reader=lambda d,day,sym:overlay(day,sym))
            self.assertEqual([x['minute_rows'] for x in r['days']],[0,0,241])
            self.assertEqual(r['days'][2]['declared_day_overlay_state'],
                             'LOCAL_DAY_OVERLAY_CONTENT_SHA_VERIFIED_RAW_DIAGNOSTICS')

    def test_two_241_days_verified_under_one_overlay_state(self):
        with TemporaryDirectory() as root:
            digest=source(root,stock_day('2026-11-10')+stock_day('2026-11-11'))
            r=X.inspect(**args(root,digest),overlay_reader=lambda p,d,s:overlay(d,s))
            self.assertEqual(r['minute_rows_checked'],482)
            self.assertEqual(r['day_overlay_status_counts']['LOCAL_DAY_OVERLAY_CONTENT_SHA_VERIFIED_RAW_DIAGNOSTICS'],2)
            self.assertEqual(r['local_day_overlay_state_sha256_if_observed'],'a'*64)

    def test_overlay_state_mutation_between_days_fail_closed(self):
        with TemporaryDirectory() as root:
            digest=source(root,stock_day('2026-11-10')+stock_day('2026-11-11'))
            def changing(p,d,s):
                return overlay(d,s,live_state_bytes_sha256=('b' if d.endswith('11') else 'a')*64)
            with self.assertRaisesRegex(X.OverlayPairError,'STATE_CHANGED_BETWEEN_DATES'):
                X.inspect(**args(root,digest),overlay_reader=changing)

    def test_missing_overlay_day_receipt_is_only_declared_absent(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            def unavailable(p,d,s):
                raise OVERLAY.OverlayError('DAY_NOT_FOUND_IN_PINNED_LIVE_STATE')
            r=X.inspect(**args(root,digest),overlay_reader=unavailable)
            self.assertEqual(r['days'][0]['declared_day_overlay_state'],
                             'DECLARED_DAY_OVERLAY_NOT_REGISTERED')
            self.assertIsNone(r['local_day_overlay_state_sha256_if_observed'])
            self.assertFalse(r['six_field_quality_passed'])

    def test_target_absent_in_declared_day_is_soft_not_certified(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            def missing(p,d,s):
                raise DAY.DayContentError('TARGET_EQUITY_NOT_IN_DAY_EXPORT')
            r=X.inspect(**args(root,digest),overlay_reader=missing)
            self.assertEqual(r['days'][0]['declared_day_overlay_state'],
                             'TARGET_MISSING_IN_DECLARED_DAY')
            self.assertFalse(r['data_source_independence_or_provider_identity_certified'])

    def test_unknown_overlay_integrity_problem_must_raise(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            def corrupt(p,d,s):
                raise OVERLAY.OverlayError('SOURCE_METADATA_CHANGED_DURING_READ')
            with self.assertRaisesRegex(OVERLAY.OverlayError,'SOURCE_METADATA_CHANGED'):
                X.inspect(**args(root,digest),overlay_reader=corrupt)

    def test_forged_overlay_provider_authority_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            with self.assertRaisesRegex(X.OverlayPairError,'SCOPE_OR_AUTHORITY'):
                X.inspect(**args(root,digest),
                          overlay_reader=lambda p,d,s:overlay(d,s,provider_identity_authenticated=True))

    def test_forged_production_authority_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            with self.assertRaisesRegex(X.OverlayPairError,'SCOPE_OR_AUTHORITY'):
                X.inspect(**args(root,digest),
                          overlay_reader=lambda p,d,s:overlay(d,s,market_data_write_authorized=True))

    def test_forged_raw_zip_byte_proof_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            with self.assertRaisesRegex(X.OverlayPairError,'SCOPE_OR_AUTHORITY'):
                X.inspect(**args(root,digest),
                          overlay_reader=lambda p,d,s:overlay(d,s,tdx_raw_zip_bytes_verified=True))

    def test_forged_overlay_symbol_or_day_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            for field,value in [('symbol','SH600000'),('day','2026-11-11')]:
                with self.subTest(field=field):
                    with self.assertRaisesRegex(X.OverlayPairError,'SCOPE_OR_AUTHORITY'):
                        X.inspect(**args(root,digest),
                                  overlay_reader=lambda p,d,s:overlay(d,s,**{field:value}))

    def test_boolean_download_count_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            with self.assertRaisesRegex(X.OverlayPairError,'SCOPE_OR_AUTHORITY'):
                X.inspect(**args(root,digest),
                          overlay_reader=lambda p,d,s:overlay(d,s,qmt_history_download_calls=False))

    def test_nonfinite_or_wrong_day_ohlcva_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            v=dict(overlay()['target_ohlcva']);v['amount']=float('inf')
            with self.assertRaisesRegex(PAIR.PairError,'DAY_NONFINITE_AMOUNT'):
                X.inspect(**args(root,digest),
                          overlay_reader=lambda p,d,s:overlay(d,s,target_ohlcva=v))

    def test_real_raw_delta_nonzero_is_not_a_quality_pass(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            values=dict(overlay()['target_ohlcva']);values['volume']=12000.
            r=X.inspect(**args(root,digest),
                         overlay_reader=lambda p,d,s:overlay(d,s,target_ohlcva=values))
            self.assertEqual(r['days'][0]['raw_six_field_difference_without_calibration']['volume']['raw_delta'],12100.)
            self.assertFalse(r['paid_minutes_units_or_timestamp_calibrated'])
            self.assertFalse(r['six_field_quality_passed'])

    def test_private_minute_source_hash_change_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            with self.assertRaisesRegex(WINDOW.WindowError,'SHA_MISMATCH'):
                X.inspect(**args(root,'f'*64),overlay_reader=lambda p,d,s:overlay(d,s))

    def test_file_mutation_during_overlay_audit_rejected(self):
        with TemporaryDirectory() as root:
            digest=source(root)
            def sabotage(p,d,s):
                f=Path(root)/'probe.jsonl';f.write_bytes(f.read_bytes()+b' ')
                return overlay(d,s)
            with self.assertRaisesRegex(X.OverlayPairError,'MINUTE_SOURCE_CHANGED_DURING'):
                X.inspect(**args(root,digest),overlay_reader=sabotage)

    def test_cross_year_and_shanghai_symbol_generic(self):
        with TemporaryDirectory() as root:
            digest=source(root,stock_day('2026-10-14','600000.SH'))
            r=X.inspect(**args(root,digest,symbol='SH600000',
                               start_day='2026-10-14',end_day='2026-10-14'),
                        overlay_reader=lambda p,d,s:overlay(d,s))
            self.assertEqual(r['symbol'],'600000.SH')
            self.assertEqual(r['calendar_days'],1)

    def test_max_day_comparison_budget_is_enforced(self):
        with TemporaryDirectory() as root:
            start=datetime(2026,10,14).date()
            rows=[]
            for n in range(X.MAX_DAY_COMPARISONS+1):
                rows+=stock_day((start+timedelta(days=n)).isoformat())
            digest=source(root,rows)
            with self.assertRaisesRegex(X.OverlayPairError,'DAY_COMPARISON_BUDGET'):
                X.inspect(**args(root,digest,start_day=start.isoformat(),
                                 end_day=(start+timedelta(days=X.MAX_DAY_COMPARISONS)).isoformat()),
                          overlay_reader=lambda p,d,s:overlay(d,s))

    def test_no_market_writer_or_qmt_download_call(self):
        import inspect
        content=inspect.getsource(X)
        for forbidden in ('download_history_data(', 'get_market_data_ex(',
                          'write_bytes(', 'write_table(', 'os.replace(', 'mkdir('):
            self.assertNotIn(forbidden,content)

    def test_cli_error_does_not_print_private_evidence_path(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            rc=X.main(['--minute-evidence-root','/private/secret-QMT','--minute-file-relative','secret.jsonl',
                       '--expected-minute-sha256','a'*64,
                       '--symbol','300119.SZ','--start-day','2026-11-10',
                       '--end-day','2026-11-12','--module-root','/private/secret-DAY'])
        self.assertEqual(rc,3)
        self.assertNotIn('/private/',out.getvalue())


if __name__=='__main__': unittest.main()
