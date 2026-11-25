"""Offline simulated QMT cache triage; NEVER calls xtquant or a network."""
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from unittest.mock import MagicMock
import audit_market_qmt_cache_readonly as p

NINE=['SH605336','SZ300119','SZ300120','SZ300121','SZ300122','SZ300123','SZ300124','SZ300125','SZ300462']

def report():
    return {'run_receipt_sha256':p.RUN_SHA,
            'stocks':[{'symbol':sym,'category':('OFFICIAL_DAY_OHLC_MISMATCH' if sym in (NINE[0],NINE[-1]) else 'QMT_RAW_ONE_MINUTE_MISSING')} for sym in NINE]}

def reference():
    return {sym: {'open':float(i+1), 'high':float(i+2), 'low':float(i+0.5),'close':float(i+1.5),'volume':100.,'amount':300.} for i,sym in enumerate(NINE)}

class CacheProbeTests(unittest.TestCase):
    def setUp(self):
        self.r=report();self.ref=reference();self.u=MagicMock()
        self.u.P.normalize_frame.return_value=[{'open':15.0,'datetime_cn':'2026-11-25T09:31:00+08:00'}]*240
        self.target=date(2026,11,25)
    def audit(self, payload):
        return p.inspect_cache(self.r,payload,self.u,self.ref,self.target)
    def test_all_missing_distinct_and_not_repaired(self):
        out=self.audit({})
        self.assertEqual(out['original_quarantine_count'],9)
        self.assertEqual(out['still_no_qmt_bars'],9)
        self.assertEqual(out['cached_now_valid'],0)
        self.assertFalse(out['market_data_written'])
        self.assertTrue(out['internal_xtquant_side_effects_not_audited'])
        self.assertEqual(self.u.P.normalize_frame.call_count,0)
    def test_two_still_rejected_seven_unavailable(self):
        payload={NINE[i][2:]+'.'+NINE[i][:2]:object() for i in (0,8)}
        self.u.normal_qmt_day.side_effect=ValueError('Independent official DAY materialized OHLC discrepancy: open')
        out=self.audit(payload)
        self.assertEqual(out['still_no_qmt_bars'],7)
        self.assertEqual(out['cached_now_valid'],0)
        self.assertEqual(sum(x['current_qmt_cache_status']=='CACHE_PRESENT_STILL_REJECTED' for x in out['stocks']),2)
        self.assertEqual(self.u.normal_qmt_day.call_count,2)
    def test_cached_now_valid_is_not_committed(self):
        payload={NINE[i][2:]+'.'+NINE[i][:2]:object() for i in (1,2,3)}
        out=self.audit(payload)
        self.assertEqual(out['cached_now_valid'],3)
        self.assertFalse(any(x['data_repaired'] for x in out['stocks']))
        self.assertFalse(out['market_data_written'])
    def test_empty_frame_classified(self):
        self.u.P.normalize_frame.return_value=[]
        out=self.audit({'605336.SH':object()})
        self.assertEqual(out['stocks'][0]['current_qmt_cache_status'],'CACHE_HAS_ZERO_ROWS')
        self.u.normal_qmt_day.assert_not_called()
    def test_invalid_frame_classified(self):
        self.u.P.normalize_frame.side_effect=ValueError('nonfinite')
        out=self.audit({'605336.SH':object()})
        self.assertEqual(out['stocks'][0]['current_qmt_cache_status'],'CACHE_FRAME_INVALID')
        self.assertIn('nonfinite',out['stocks'][0]['validation_error'])
    def test_payload_not_dict_fails_closed(self):
        with self.assertRaisesRegex(p.TriageError,'PAYLOAD_NOT_DICT'):
            self.audit(None)
    def test_duplicate_symbol_refused(self):
        self.r['stocks'][-1]['symbol']=self.r['stocks'][0]['symbol']
        with self.assertRaisesRegex(p.TriageError,'EXACT_NINE'):
            self.audit({})
    def test_only_eight_refused(self):
        self.r['stocks'].pop()
        with self.assertRaisesRegex(p.TriageError,'EXACT_NINE'):
            self.audit({})
    def test_official_reference_required(self):
        self.ref.pop('SZ300462')
        with self.assertRaisesRegex(p.TriageError,'NO_INDEPENDENT_OFFICIAL_DAY'):
            self.audit({})
    def test_pin_fails_changed_canonical_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'update_market.py').write_text('# changed',encoding='utf-8')
            with self.assertRaisesRegex(p.TriageError,'BLOB_CHANGED_STOP'):
                p.validate_source(root)
    def test_opt_in_required_before_import_or_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(p.main(['--module-root',tmp]),3)
    def test_wrong_receipt_sha_refused_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(p.main(['--module-root',tmp,'--confirm-qmt-cache-query','--expected-run-sha256','f'*64]),3)

if __name__=='__main__':unittest.main()
