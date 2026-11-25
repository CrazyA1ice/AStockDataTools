"""QMT seven-symbol single-day cache writer tests; no real QMT or project writes."""
from __future__ import annotations
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_audit_market_qmt_seven_coverage_readonly import make, GRID
import qmt_seven_single_day_cache_refresh as M


def production_mock():
    u=SimpleNamespace()
    u.P=SimpleNamespace(
        GRID=set(GRID),
        BASE=Path('C:/synthetic/qmt_private'),
        normalize_frame=Mock(side_effect=lambda frame, *a: frame if frame is not None else []),
        sha_bytes=Mock(return_value='pin'),
        canonical=Mock(return_value=b'calibration'))
    u.S=SimpleNamespace(
        _json=Mock(side_effect=[{'calibration_passed':True,'providers':{'SZ':{},'SH':{},'STAR':{}}},
                                {'qmt_calibration_sha256':'pin'}]),
        STATE_FILE=Path('C:/synthetic/ledger'))
    official={s:{'open':5,'high':6,'low':4,'close':5,'volume':10,'amount':100}
              for s in M.STOCKS}
    official.update({f'SH{i:06}':{} for i in range(5208)})
    assert len(official)==5215
    u._reference_for_day=Mock(return_value=official)
    u.normal_qmt_day=Mock(return_value=SimpleNamespace(num_rows=240))
    return u


def evidence():
    return {'accepted':5206, 'expected':5215, 'quarantined':9,
            'stocks':[{'symbol':s,'category':'QMT_RAW_ONE_MINUTE_MISSING'} for s in M.STOCKS]
                    +[{'symbol':'SH605336','category':'OFFICIAL_DAY_OHLC_MISMATCH'},
                      {'symbol':'SZ300462','category':'OFFICIAL_DAY_OHLC_MISMATCH'}]}


def old_cache():
    return {s[2:]+'.'+s[:2]:make('2026-11-20')+make('2026-11-23')+make('2026-11-24') for s in M.STOCKS}


def after_cache(valid=True):
    return {s[2:]+'.'+s[:2]:(make('2026-11-25') if valid else []) for s in M.STOCKS}


def backend(old=None, after=None):
    xt=SimpleNamespace(
        get_market_data_ex=Mock(side_effect=[old if old is not None else old_cache(),
                                            after if after is not None else after_cache()]),
        download_history_data=Mock())
    return xt


def call(approve=True, *, xt=None, u=None, report=None, pin=None):
    u=u or production_mock()
    xt=xt or backend()
    audit=Mock(return_value=evidence() if report is None else report)
    pins=Mock() if pin is None else pin
    return M.refresh(Path('C:/synthetic/project/ParquetLiveSync'),approve=approve,
                     xtdata=xt,updater=u,source_audit=audit,source_pins=pins),xt,u,audit,pins


class SevenRefreshTests(unittest.TestCase):
    def test_default_dry_run_has_no_qmt_call(self):
        xt=backend()
        result,_,_,aud,pins=call(approve=False,xt=xt)
        self.assertIn('PLAN_ONLY_NO_QMT_CALLS',result['status'])
        self.assertFalse(result['qmt_downloads_authorized'])
        self.assertEqual(result['qmt_download_calls'],0)
        self.assertFalse(result['data_quality_cleared'])
        xt.get_market_data_ex.assert_not_called()
        xt.download_history_data.assert_not_called()
        aud.assert_not_called()
        pins.assert_not_called()

    def test_cli_default_plan_only(self):
        action=Mock(return_value=M.plan())
        out=StringIO()
        with redirect_stdout(out):
            code=M.main(['--module-root','C:/synthetic'],action=action)
        self.assertEqual(code,0)
        action.assert_called_once_with(Path('C:/synthetic'),approve=False)
        self.assertFalse(json.loads(out.getvalue())['production_merge_authorized'])

    def test_cli_optin_is_explicit_and_unambiguous(self):
        action=Mock(return_value={**M.plan(),
                'all_seven_passed_current_market_validator':False})
        out=StringIO()
        with redirect_stdout(out):
            code=M.main(['--module-root','C:/synthetic',
                         '--approve-qmt-cache-write-exact-seven-nov25'],action=action)
        self.assertEqual(code,3)
        action.assert_called_once_with(Path('C:/synthetic'),approve=True)

    def test_wrong_original_evidence_stops_before_qmt(self):
        bad=evidence();bad['quarantined']=8
        xt=backend()
        with self.assertRaisesRegex(M.RefreshError,'ORIGINAL_NINE'):
            call(xt=xt,report=bad)
        xt.get_market_data_ex.assert_not_called()
        xt.download_history_data.assert_not_called()

    def test_official_day_missing_stops_before_qmt(self):
        u=production_mock();u._reference_for_day.return_value={'SZ300119':{}}
        xt=backend()
        with self.assertRaisesRegex(M.RefreshError,'INDEPENDENT_OFFICIAL'):
            call(u=u,xt=xt)
        xt.get_market_data_ex.assert_not_called()
        xt.download_history_data.assert_not_called()

    def test_paid_calibration_wrong_pin_stops_before_qmt(self):
        u=production_mock();u.P.sha_bytes.return_value='different'
        xt=backend()
        with self.assertRaisesRegex(M.RefreshError,'PAID_MINUTE'):
            call(u=u,xt=xt)
        xt.get_market_data_ex.assert_not_called()
        xt.download_history_data.assert_not_called()

    def test_previous_three_days_must_have_241_each(self):
        cache=old_cache();cache['300119.SZ']=make('2026-11-24')
        xt=backend(old=cache)
        with self.assertRaisesRegex(M.RefreshError,'COVERAGE_CHANGED_SZ300119'):
            call(xt=xt)
        xt.download_history_data.assert_not_called()

    def test_target_date_already_present_blocks_download(self):
        cache=old_cache();cache['300119.SZ']+=make('2026-11-25')
        xt=backend(old=cache)
        with self.assertRaisesRegex(M.RefreshError,'COVERAGE_CHANGED_SZ300119'):
            call(xt=xt)
        xt.download_history_data.assert_not_called()

    def test_missing_original_stock_key_blocks_download(self):
        cache=old_cache();cache.pop('300123.SZ')
        xt=backend(old=cache)
        with self.assertRaisesRegex(M.RefreshError,'COVERAGE_CHANGED_SZ300123'):
            call(xt=xt)
        xt.download_history_data.assert_not_called()

    def test_valid_exact_seven_downloads_one_day_and_in_memory_validation(self):
        result,xt,u,aud,pins=call()
        audit_args=aud.call_args
        self.assertEqual(audit_args.args[1], '2026-11-25')
        self.assertEqual(audit_args.args[2],M.RUN_SHA)
        self.assertTrue(audit_args.kwargs['verify_parquet'])
        pins.assert_called_once()
        self.assertEqual(xt.get_market_data_ex.call_count,2)
        self.assertEqual(xt.download_history_data.call_count,7)
        for index,args in enumerate(xt.download_history_data.call_args_list):
            s=M.STOCKS[index]
            self.assertEqual(args.args,(s[2:]+'.'+s[:2],))
            self.assertEqual(args.kwargs,{'period':'1m','start_time':'20261125','end_time':'20261125'})
        for args in xt.get_market_data_ex.call_args_list:
            self.assertEqual(args.kwargs['stock_list'],[s[2:]+'.'+s[:2] for s in M.STOCKS])
            self.assertFalse(args.kwargs['fill_data'])
        self.assertEqual(result['qmt_history_download_calls'],7)
        self.assertTrue(result['all_seven_passed_current_market_validator'])
        self.assertFalse(result['production_merge_authorized'])
        self.assertFalse(result['market_files_modified'])
        self.assertFalse(result['data_quality_cleared'])
        self.assertEqual(u.normal_qmt_day.call_count,7)

    def test_stop_on_third_qmt_provider_failure_no_auto_retry(self):
        xt=backend()
        xt.download_history_data.side_effect=[None,None,RuntimeError('provider unavailable')]
        with self.assertRaisesRegex(M.RefreshError,'PARTIAL_STOP_2_COMPLETED_NEXT_300121.SZ_RuntimeError'):
            call(xt=xt)
        self.assertEqual(xt.download_history_data.call_count,3)
        self.assertEqual(xt.get_market_data_ex.call_count,1)

    def test_all_download_calls_not_proof_of_cache_bars(self):
        xt=backend(after=after_cache(False))
        res,xt,_,_,_=call(xt=xt)
        self.assertEqual(xt.download_history_data.call_count,7)
        self.assertFalse(res['all_seven_passed_current_market_validator'])
        self.assertTrue(all(x['status']=='CACHE_REFRESH_NO_FULL_NATIVE_DAY' for x in res['stocks']))
        self.assertFalse(res['production_merge_authorized'])

    def test_one_official_validator_rejection_keeps_candidate_quarantined(self):
        u=production_mock();u.normal_qmt_day.side_effect=[SimpleNamespace(num_rows=240)]*3+[ValueError('official high mismatch')]+[SimpleNamespace(num_rows=240)]*3
        res,_,_,_,_=call(u=u)
        self.assertFalse(res['all_seven_passed_current_market_validator'])
        self.assertEqual(res['stocks'][3]['status'],'CACHE_REFRESH_REJECTED_BY_ORIGINAL_VALIDATOR')
        self.assertTrue(res['original_quarantines_retained'])

    def test_bad_post_download_dictionary_stops_with_no_project_write(self):
        xt=backend()
        xt.get_market_data_ex.side_effect=[old_cache(),None]
        with self.assertRaisesRegex(M.RefreshError,'POST_DOWNLOAD_QMT_RESPONSE_INVALID'):
            call(xt=xt)
        self.assertEqual(xt.download_history_data.call_count,7)

    def test_exception_from_source_pin_shortcircuits_before_qmt(self):
        xt=backend();pin=Mock(side_effect=M.RefreshError('SOURCE_PIN_CHANGED'))
        with self.assertRaisesRegex(M.RefreshError,'SOURCE_PIN_CHANGED'):
            call(xt=xt,pin=pin)
        xt.get_market_data_ex.assert_not_called()
        xt.download_history_data.assert_not_called()


if __name__=='__main__':unittest.main()
