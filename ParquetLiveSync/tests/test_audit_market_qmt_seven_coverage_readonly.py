"""Seven QMT stocks / four-session local-cache-only audit regressions."""
from datetime import datetime,date
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    import audit_market_qmt_cache_readonly
except ModuleNotFoundError:
    sys.modules['audit_market_qmt_cache_readonly']=SimpleNamespace(
      RUN_DATE='2026-11-25',RUN_SHA='72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837',
      TriageError=ValueError,source_modules=lambda f:None,git_blob_sha=lambda f:'invalid')
try:
    import audit_market_quarantine_readonly
except ModuleNotFoundError:
    sys.modules['audit_market_quarantine_readonly']=SimpleNamespace(audit=lambda *a,**kw:None)
from audit_market_qmt_seven_coverage_readonly import (STOCKS,DAYS,analyze_existing_cache,run_audit,TriageError)

GRID=([(9,m) for m in range(30,60)]+[(10,m) for m in range(60)]+[(11,m) for m in range(31)]
      + [(13,m) for m in range(1,60)] + [(14,m) for m in range(60)] + [(15,0)])
assert len(GRID)==241

def make(day,full=True):
    count=241 if full else 37
    return [{'datetime_cn':f'{day}T{h:02}:{m:02}:00+08:00'} for h,m in GRID[:count]]

def mock_production():
    P=SimpleNamespace(GRID=set(GRID),normalize_frame=mock.Mock(side_effect=lambda frame,*args:frame))
    obj=SimpleNamespace(P=P,_reference_for_day=mock.Mock(return_value={**{s:{} for s in STOCKS},
                              **{f'SH{i:06}':{} for i in range(5208)}}))
    return obj


class SevenTests(unittest.TestCase):
    def setUp(self):self.u=mock_production()
    def check(self,payload):return analyze_existing_cache(payload,self.u)
    def test_fixed_seven_symbols_and_days(self):
        self.assertEqual(STOCKS,('SZ300119','SZ300120','SZ300121','SZ300122','SZ300123','SZ300124','SZ300125'))
        self.assertEqual(len(DAYS),4)
    def test_empty_frames_match_one_day_unavailable(self):
        payload={s[2:]+'.'+s[:2]:[] for s in STOCKS}
        result=self.check(payload)
        self.assertEqual(result['counts_by_status'],{'QMT_WINDOW_EMPTY':7})
        self.assertFalse(result['project_market_files_modified'])
        self.assertFalse(result['history_download_called'])
    def test_no_key_distinguished_from_empty(self):
        result=self.check({})
        self.assertEqual(result['counts_by_status'],{'QMT_STOCK_KEY_MISSING':7})
    def test_older_data_but_no_nov25(self):
        payload={'300119.SZ':make('2026-11-24')}
        r=self.check(payload)['stocks'][0]
        self.assertEqual(r['status'],'OLDER_CACHE_PRESENT_NOV25_EMPTY')
        self.assertEqual(r['rows_by_day']['2026-11-24'],241)
        self.assertEqual(r['rows_by_day']['2026-11-25'],0)
    def test_nov25_full_grid_is_not_accepted(self):
        out=self.check({'300119.SZ':make('2026-11-25')})['stocks'][0]
        self.assertEqual(out['status'],'NOV25_CACHED_FULL_GRID_NOT_VALIDATED')
        self.assertTrue(out['nov25_complete_grid_in_cache'])
        self.assertFalse(out['data_repaired'])
    def test_nov25_partial_grid_not_accepted(self):
        out=self.check({'300119.SZ':make('2026-11-25',False)})['stocks'][0]
        self.assertEqual(out['status'],'NOV25_CACHED_PARTIAL_GRID_NOT_VALIDATED')
    def test_exact_240_grid_accepted_only_as_shape(self):
        out=self.check({'300119.SZ':make('2026-11-25')[1:]})['stocks'][0]
        self.assertTrue(out['nov25_complete_grid_in_cache'])
        self.assertFalse(out['data_repaired'])
    def test_bad_qmt_result_fails_closed(self):
        with self.assertRaisesRegex(TriageError,'BATCH_NOT_DICT'):
            self.check(None)
    def test_bad_datetime_inside_payload_classified(self):
        self.u.P.normalize_frame.side_effect=ValueError('bad QMT source frame')
        out=self.check({'300119.SZ':object()})['stocks'][0]
        self.assertEqual(out['status'],'QMT_CACHE_FRAME_INVALID')
    def test_unexpected_window_date_is_invalid(self):
        out=self.check({'300119.SZ':make('2026-11-19')})['stocks'][0]
        self.assertEqual(out['status'],'QMT_CACHE_FRAME_INVALID')
    def test_zero_query_without_optin(self):
        with self.assertRaisesRegex(TriageError,'EXPLICIT_SEVEN'):
            run_audit(Path('/tmp/missing'),confirm=False)
    def test_original_quarantine_evidence_fail_before_qmt(self):
        aud=mock.Mock(return_value={'accepted':5206,'quarantined':8,
          'stocks':[{'symbol':s,'category':'QMT_RAW_ONE_MINUTE_MISSING'} for s in STOCKS]})
        xt=SimpleNamespace(get_market_data_ex=mock.Mock())
        with mock.patch('audit_market_qmt_seven_coverage_readonly.verify_dependencies'):
            with self.assertRaisesRegex(TriageError,'ORIGINAL_SEVEN'):
                run_audit('/tmp/fake',confirm=True,updater=self.u,xtdata=xt,forensic_audit=aud)
        xt.get_market_data_ex.assert_not_called()
    def test_official_universe_fails_before_qmt(self):
        aud=mock.Mock(return_value={'accepted':5206,'quarantined':9,
          'stocks':[{'symbol':s,'category':'QMT_RAW_ONE_MINUTE_MISSING'} for s in STOCKS]})
        self.u._reference_for_day.return_value={'SZ300119':{}}
        xt=SimpleNamespace(get_market_data_ex=mock.Mock())
        with mock.patch('audit_market_qmt_seven_coverage_readonly.verify_dependencies'):
            with self.assertRaisesRegex(TriageError,'OFFICIAL_DAY'):
                run_audit('/tmp/fake',confirm=True,updater=self.u,xtdata=xt,forensic_audit=aud)
        xt.get_market_data_ex.assert_not_called()
    def test_main_path_queries_once_only_and_never_downloads(self):
        aud=mock.Mock(return_value={'accepted':5206,'quarantined':9,
          'stocks':[{'symbol':s,'category':'QMT_RAW_ONE_MINUTE_MISSING'} for s in STOCKS]})
        xt=SimpleNamespace(get_market_data_ex=mock.Mock(return_value={}),download_history_data=mock.Mock())
        with mock.patch('audit_market_qmt_seven_coverage_readonly.verify_dependencies'):
            result=run_audit('/tmp/fake',confirm=True,updater=self.u,xtdata=xt,forensic_audit=aud)
        self.assertEqual(result['counts_by_status'],{'QMT_STOCK_KEY_MISSING':7})
        xt.get_market_data_ex.assert_called_once()
        xt.download_history_data.assert_not_called()
        k=xt.get_market_data_ex.call_args.kwargs
        self.assertEqual(k['stock_list'],[s[2:]+'.'+s[:2] for s in STOCKS])
        self.assertEqual(k['start_time'],'20261120')
        self.assertEqual(k['end_time'],'20261125')
        self.assertEqual(k['period'],'1m')
        self.assertFalse(k['fill_data'])

if __name__=='__main__':unittest.main()
