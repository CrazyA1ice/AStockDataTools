"""Offline QMT recovery contracts: per-day evidence, SHA safety, no market writes."""
from datetime import date,datetime
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_1m_recover",HERE/"qmt_1m_recover.py")
R=importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def bars(day,code="600000.SH",low=9.99):
    output=[]
    for h,m in sorted(R.P.GRID):
        output.append({"datetime_cn":datetime(day.year,day.month,day.day,
            h,m,tzinfo=R.P.CN).isoformat(),"symbol":code,
            "open":10.,"high":10.01,"low":low,"close":10.,
            "volume":100.,"amount":10000.})
    return output


class SyntheticSource:
    def __init__(self,rows):
        self.rows=rows
        self.columns=(*R.Q.FIELDS,)
    def iterrows(self):
        for bar in self.rows:
            ts=bar["datetime_cn"][:10].replace("-","")+bar["datetime_cn"][11:16].replace(":","")+"00"
            yield ts,{k:bar[k] for k in R.Q.FIELDS}


class FakeXtdata:
    def __init__(self,code,rows):
        self.code=code
        self.rows=rows
        self.calls=0
    def download_history_data(self,*args,**kwargs):
        self.calls+=1
    def get_market_data_ex(self,**kwargs):
        self.kwargs=kwargs
        return {self.code:SyntheticSource(self.rows)}


class RecoveryTests(unittest.TestCase):
    def test_recover_one_bad_day_but_preserve_one_good_day(self):
        first,second=date(2026,10,14),date(2026,10,15)
        code="600000.SH"
        fake=FakeXtdata(code,bars(first)+bars(second))
        raw=R.fetch_raw_by_day(fake,code,first,second)
        self.assertEqual(fake.calls,1)
        self.assertFalse(fake.kwargs["fill_data"])
        self.assertEqual(fake.kwargs["dividend_type"],"none")
        self.assertEqual(len(raw[first]),241)
        ref={"open":10.,"high":10.01,"low":9.99,"close":10.}
        accepted,detail=R.check_day(code,first,raw[first],ref)
        self.assertEqual(len(accepted),241)
        self.assertTrue(all(detail["match"].values()))
        wrong={**ref,"high":10.5}
        rejected,bad=R.check_day(code,second,raw[second],wrong)
        self.assertIsNone(rejected)
        self.assertEqual(bad["reason"],"QMT_OFFICIAL_DAY_OHLC_MISMATCH")
        self.assertFalse(bad["match"]["high"])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            saved=R.save_partial(root,code,accepted,[str(first)],{str(second):bad},"test-fingerprint")
            self.assertEqual(saved["rows"],241)
            self.assertFalse(saved["market_modified"])
            validated=R.validate_recovery_receipt(root,code,"test-fingerprint",[str(first),str(second)])
            self.assertEqual(validated["approved_days"],[str(first)])
            with self.assertRaisesRegex(ValueError,"already exists"):
                R.save_partial(root,code,accepted,[str(first)],{str(second):bad},"test-fingerprint")

    def test_bad_source_price_is_quarantined_without_losing_other_day(self):
        first,second=date(2026,10,14),date(2026,10,15)
        code="600000.SH"
        raw=R.fetch_raw_by_day(FakeXtdata(code,bars(first)+bars(second,low=0.)),code,first,second)
        ref={"open":10.,"high":10.01,"low":9.99,"close":10.}
        accepted,_=R.check_day(code,first,raw[first],ref)
        self.assertEqual(len(accepted),241)
        with self.assertRaisesRegex(ValueError,"OHLC"):
            R.check_day(code,second,raw[second],ref)

    def test_windows_transient_lock_retry_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src=root/"a";dst=root/"b"
            src.write_text("secret")
            real=R.os.replace
            calls=[]
            def replace(a,b):
                calls.append((a,b))
                if len(calls)<3:
                    raise PermissionError("simulated Windows AV lock")
                return real(a,b)
            with patch.object(R.os,"replace",side_effect=replace):
                R.retry_private_atomic(src,dst,sleeper=lambda _:None)
            self.assertEqual(len(calls),3)
            self.assertEqual(dst.read_text(),"secret")

    def test_detect_recovery_sha_tamper(self):
        day=date(2026,10,14);code="600000.SH"
        ref={"open":10.,"high":10.01,"low":9.99,"close":10.}
        accepted,_=R.check_day(code,day,[{"time":datetime.fromisoformat(x["datetime_cn"]),
            **{k:x[k] for k in R.Q.FIELDS}} for x in bars(day)],ref)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            result=R.save_partial(root,code,accepted,[str(day)],{},"a")
            source=root/"source_parquet"/"600000_SH.parquet"
            with source.open("ab") as f:
                f.write(b"CHANGED")
            with self.assertRaisesRegex(ValueError,"SHA invalid"):
                R.validate_recovery_receipt(root,code,"a",[str(day)])

    def test_full_stock_original_sha_audit_and_undocumented_stock_refused(self):
        code="600000.SH";day=date(2026,10,14)
        reference={"open":10.,"high":10.01,"low":9.99,"close":10.,
                   "volume":24100.,"amount":2410000.}
        expected={day:{code:reference}}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            fake=FakeXtdata(code,bars(day))
            item,created=R.P.qmt_stage_stock(code,expected,day,day,{},root,fake)
            self.assertTrue(created)
            accepted=R.validate_original(root,expected,[code],progress=lambda _:None)
            self.assertEqual(set(accepted),{code})
            with self.assertRaisesRegex(ValueError,"Unexpected or duplicate"):
                R.validate_original(root,expected,[],progress=lambda _:None)

    def test_empty_recovery_receipt_and_disjoint_days(self):
        day=date(2026,10,14)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            R.save_partial(root,"600000.SH",[],[],{str(day):{"reason":"invalid source"}},"b")
            doc=R.validate_recovery_receipt(root,"600000.SH","b",[str(day)])
            self.assertEqual(doc["rows"],0)
            self.assertIsNone(doc["sha256"])
            self.assertEqual(list((root/"source_parquet").glob("*.parquet")),[])

if __name__=="__main__":
    unittest.main()
