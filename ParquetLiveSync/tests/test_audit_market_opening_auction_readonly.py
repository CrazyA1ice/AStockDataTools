"""Mocked no-network checks for 2-stock official open/auction provenance."""
from datetime import date, datetime, timedelta, timezone
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Standalone scratch fallback only. Real PR #258 imports the actual stacked
# PR #256/#257 modules when present.
try:
    import audit_market_qmt_cache_readonly
except ModuleNotFoundError:
    q=SimpleNamespace(RUN_DATE='2026-11-25',RUN_SHA='72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837',
                  TriageError=ValueError,git_blob_sha=lambda f:'bad',source_modules=lambda f:None)
    sys.modules['audit_market_qmt_cache_readonly']=q
try:
    import audit_market_quarantine_readonly
except ModuleNotFoundError:
    sys.modules['audit_market_quarantine_readonly']=SimpleNamespace(audit=lambda *a,**kw:None)
from audit_market_opening_auction_readonly import (replay_one, run_audit,
    verify_dependencies, STOCKS, PINNED_MODULE_BLOBS, TriageError)

CN=timezone(timedelta(hours=8))
GRID=([(9,m) for m in range(30,60)]+[(10,m) for m in range(60)]+[(11,m) for m in range(31)]
      + [(13,m) for m in range(1,60)] + [(14,m) for m in range(60)] + [(15,0)])
assert len(GRID)==241


def rows(auction=True):
    data=[]
    for i,(h,m) in enumerate(GRID):
        data.append({'datetime_cn': f'2026-11-25T{h:02d}:{m:02d}:00+08:00',
        'open':7.69 if i==0 else 7.7,'high':7.8,'low':7.60,'close':7.7,
        'volume':10. if i==0 and auction else (0. if i==0 else 2.),
        'amount':100. if i==0 and auction else (0. if i==0 else 20.)})
    return data


def fake_update():
    u=SimpleNamespace()
    u.B=SimpleNamespace(_calibration=mock.Mock(return_value={'offset_ms':0,'volume_factor':1.,'amount_factor':1.}))
    u.L=SimpleNamespace(normal_symbol=lambda code:code[-2:]+code[:6])
    u.P=SimpleNamespace(stamp_ms=lambda value:int(datetime.fromisoformat(value).timestamp()*1000),
                        normalize_frame=lambda frame,*args:frame,BASE=Path('/tmp/fake'))
    def fold(original, offset, month):
        assert len(original)==241
        folded=[x.copy() for x in original[1:]]
        if original[0]['volume']>0:
            folded[0]['open']=original[0]['open']
            folded[0]['high']=max(original[0]['high'],folded[0]['high'])
            folded[0]['low']=min(original[0]['low'],folded[0]['low'])
            folded[0]['volume']+=original[0]['volume']
            folded[0]['amount']+=original[0]['amount']
            return folded,'REAL_AUCTION_FOLDED_TO_0931'
        return folded,'ZERO_PLACEHOLDER'
    u.S=SimpleNamespace(_fold_241_day=mock.Mock(side_effect=fold),
                        _json=mock.Mock(side_effect=[{'calibration_passed':True,'providers':{'A':{},'B':{},'C':{}}},
                                                         {'qmt_calibration_sha256':'pinned'}]),
                        STATE_FILE=Path('/tmp/dummy-ledger'))
    def check(bars, expected):
        if not math.isclose(bars[0]['open'],expected['open'],rel_tol=.006,abs_tol=.04):
            raise ValueError('Independent official DAY materialized OHLC discrepancy: open')
    u.verify_materialized_ohlc=mock.Mock(side_effect=check)
    def complete(raw,code,day,expected,calibration):
        result,_=fold([{'ts':u.P.stamp_ms(r['datetime_cn']),'symbol':'SH605336',**{k:r[k] for k in ('open','high','low','close','volume','amount')}} for r in raw],0,day.strftime('%Y-%m'))
        check(result,expected)
    u.normal_qmt_day=mock.Mock(side_effect=complete)
    u.LIVE=SimpleNamespace(read_state=mock.Mock(return_value={'days':{'2026-11-25':{'sha256':'a'*64,'receipt_sha256':'b'*64}}}))
    u._reference_for_day=mock.Mock(return_value={**{'SH000001':{}} ,**{s:{'open':7.62,'high':7.8,'low':7.60,'close':7.95,'volume':490.,'amount':4900.} for s in STOCKS},
                                       **{f'SZ{i:06}':{} for i in range(5212)}})
    u.P.sha_bytes=lambda v:'pinned'
    u.P.canonical=lambda v:b'calibration'
    return u


class AuctionTests(unittest.TestCase):
    def setUp(self):
        self.u=fake_update()
        self.expected={'open':7.62,'high':7.8,'low':7.60,'close':7.95,'volume':490.,'amount':4900.}
        self.day=date(2026,11,25)
    def test_true_auction_uses_0930_open(self):
        out=replay_one(self.u,'605336.SH',rows(True),self.expected,{},self.day)
        self.assertEqual(out['auction_kind'],'REAL_AUCTION_FOLDED_TO_0931')
        self.assertEqual(out['raw_0930_open'],7.69)
        self.assertEqual(out['raw_0931_open'],7.7)
        self.assertEqual(out['folded_0931_open'],7.69)
        self.assertEqual(out['folded_minus_official'],.07)
        self.assertFalse(out['open_isclose'])
        self.assertIn('discrepancy: open',out['full_original_validation_error'])
        self.assertFalse(out['all_data_changes_committed'])
    def test_full_ohlcva_report_does_not_hide_later_field_failures(self):
        out=replay_one(self.u,'605336.SH',rows(True),self.expected,{},self.day)
        fields=out['field_comparisons']
        self.assertEqual(set(fields), {'open','high','low','close','volume','amount'})
        self.assertFalse(fields['open']['within_existing_tolerance'])
        self.assertTrue(fields['high']['within_existing_tolerance'])
        self.assertFalse(fields['close']['within_existing_tolerance'])
        self.assertEqual(out['folded_day_ohlcva']['open'],7.69)
        self.assertEqual(out['official_day_ohlcva']['open'],7.62)
        self.assertFalse(out['outside_official_high_low_envelope'])
        self.assertFalse(out['all_data_changes_committed'])
    def test_placeholder_uses_0931_open(self):
        out=replay_one(self.u,'605336.SH',rows(False),self.expected,{},self.day)
        self.assertEqual(out['auction_kind'],'ZERO_PLACEHOLDER')
        self.assertEqual(out['folded_0931_open'],7.7)
        self.assertEqual(out['raw_0930_volume'],0)
    def test_day_open_within_tolerance(self):
        self.expected['open']=7.67
        out=replay_one(self.u,'605336.SH',rows(True),self.expected,{},self.day)
        self.assertTrue(out['open_isclose'])
        self.assertIsNone(out['folded_ohlc_validation_error'])
    def test_only_241_bars(self):
        with self.assertRaisesRegex(TriageError,'241'):
            replay_one(self.u,'605336.SH',rows()[:-1],self.expected,{},self.day)
    def test_clock_must_start_0930(self):
        r=rows();r[0]['datetime_cn']='2026-11-25T09:32:00+08:00'
        with self.assertRaisesRegex(TriageError,'FIRST_CLOCK'):
            replay_one(self.u,'605336.SH',r,self.expected,{},self.day)
    def test_timezone_rejected(self):
        r=rows();r[0]['datetime_cn']='2026-11-25T09:30:00+09:00'
        with self.assertRaisesRegex(TriageError,'TIMEZONE'):
            replay_one(self.u,'605336.SH',r,self.expected,{},self.day)
    def test_production_verdict_must_agree_with_replay(self):
        self.u.normal_qmt_day.side_effect=None
        with self.assertRaisesRegex(TriageError,'DIVERGED'):
            replay_one(self.u,'605336.SH',rows(True),self.expected,{},self.day)
    def test_auction_kind_uncertified_is_failure(self):
        self.u.S._fold_241_day.side_effect=lambda original,offset,month:(original[1:],'UNKNOWN')
        with self.assertRaisesRegex(TriageError,'UNKNOWN_AUCTION'):
            replay_one(self.u,'605336.SH',rows(True),self.expected,{},self.day)
    def test_invalid_offset_refused(self):
        self.u.B._calibration.return_value={'offset_ms':1.5,'volume_factor':1.,'amount_factor':1.}
        with self.assertRaisesRegex(TriageError,'UNEXPECTED_OFFSET'):
            replay_one(self.u,'605336.SH',rows(True),self.expected,{},self.day)
    def test_pins_accept_only_all_exact_git_blobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with mock.patch('audit_market_opening_auction_readonly.git_blob_sha',
                            side_effect=lambda path:PINNED_MODULE_BLOBS[path.name]):
                verify_dependencies(root)
    def test_pin_dependency_change_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with mock.patch('audit_market_opening_auction_readonly.git_blob_sha',return_value='other'):
                with self.assertRaisesRegex(TriageError,'CANONICAL_DEPENDENCY_CHANGED'):
                    verify_dependencies(root)
    def test_no_permission_no_query(self):
        with self.assertRaisesRegex(TriageError,'EXPLICIT_TWO_STOCK'):
            run_audit('/tmp/none',confirm=False)
    def test_real_driver_one_cached_query_zero_download(self):
        u=self.u
        # 5215 official reference entries incl both stocks.
        self.assertEqual(len(u._reference_for_day(None,None)),5215)
        xt=SimpleNamespace(get_market_data_ex=mock.Mock(return_value={'605336.SH':rows(True),'300462.SZ':rows(True)}),
                           download_history_data=mock.Mock())
        aud=mock.Mock(return_value={'accepted':5206,'quarantined':9,'expected':5215,
                                     'stocks':[{'symbol':s,'category':'OFFICIAL_DAY_OHLC_MISMATCH'} for s in STOCKS]})
        with mock.patch('audit_market_opening_auction_readonly.verify_dependencies'):
            result=run_audit('/tmp/fake',confirm=True,u=u,xtdata=xt,source_audit=aud)
        xt.get_market_data_ex.assert_called_once()
        xt.download_history_data.assert_not_called()
        self.assertEqual(xt.get_market_data_ex.call_args.kwargs['stock_list'],['605336.SH','300462.SZ'])
        self.assertEqual(len(result['stocks']),2)
        self.assertFalse(result['project_data_modified'])
        self.assertFalse(result['data_quality_cleared'])
    def test_wrong_quarantine_evidence_blocks_qmt(self):
        xt=SimpleNamespace(get_market_data_ex=mock.Mock())
        aud=mock.Mock(return_value={'accepted':5206,'quarantined':8,'expected':5215,
                                     'stocks':[{'symbol':s,'category':'OFFICIAL_DAY_OHLC_MISMATCH'} for s in STOCKS]})
        with mock.patch('audit_market_opening_auction_readonly.verify_dependencies'):
            with self.assertRaisesRegex(TriageError,'ORIGINAL_QUARANTINE'):
                run_audit('/tmp/fake',confirm=True,u=self.u,xtdata=xt,source_audit=aud)
        xt.get_market_data_ex.assert_not_called()

if __name__=='__main__':unittest.main()
