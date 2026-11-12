"""Offline tests for QMT historical calibration, safe private staging and resume."""
from datetime import date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("qmt_1m_pipeline",HERE/"qmt_1m_pipeline.py")
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def rows(day=date(2026,10,14),code="600000.SH",different_prices=False):
    slots=sorted(p.GRID)
    out=[]
    for i,(h,m) in enumerate(slots):
        dt=datetime(day.year,day.month,day.day,h,m,tzinfo=p.CN)
        price=10. + i*.05 if different_prices else 10.
        out.append({"datetime_cn":dt.isoformat(),"symbol":code,
                    "open":price,"high":price+.01,"low":price-.01,
                    "close":price,"volume":100.,"amount":10000.})
    return out


class FakeFrame:
    columns=("open","high","low","close","volume","amount")
    def __init__(self,items):
        self.items=items
    def iterrows(self):
        for item in self.items:
            yield item["datetime_cn"].replace("-","")[:8]+item["datetime_cn"][11:16].replace(":","")+"00",{
                k:item[k] for k in ("open","high","low","close","volume","amount")}


class FakeXtdata:
    def __init__(self,code,items):
        self.code=code
        self.items=items
        self.calls=0
    def download_history_data(self,*args,**kwargs):
        self.calls+=1
    def get_market_data_ex(self,**kwargs):
        return {self.code:FakeFrame(self.items)}


class QmtPipelineTests(unittest.TestCase):
    def test_grid_is_exact_241(self):
        self.assertEqual(len(p.GRID),241)
        self.assertIn((9,30),p.GRID)
        self.assertIn((11,30),p.GRID)
        self.assertIn((13,1),p.GRID)
        self.assertIn((15,0),p.GRID)
        self.assertNotIn((13,0),p.GRID)
        self.assertNotIn((12,30),p.GRID)

    def test_categories(self):
        self.assertEqual(p.category("600000.SH"),"SH_OTHER")
        self.assertEqual(p.category("000001.SZ"),"SZ")
        self.assertEqual(p.category("688001.SH"),"STAR")

    def test_full_day_grid_rejects_missing_or_ghost_minutes(self):
        day=date(2026,10,14)
        valid=rows()
        self.assertEqual(len(p.validate_full_days(valid,[day],"600000.SH")[day]),241)
        with self.assertRaisesRegex(ValueError,"NOT_EXACT_241"):
            p.validate_full_days(valid[:-1],[day],"600000.SH")
        with self.assertRaisesRegex(ValueError,"STOCK_DAY_MISMATCH"):
            p.validate_full_days(valid,[date(2026,10,15)],"600000.SH")

    def test_paid_overlap_calibration_unit_and_time(self):
        code="600000.SH"
        source=rows(day=date(2026,9,30),different_prices=True)
        original={}
        for bar in source:
            ts=p.stamp_ms(bar["datetime_cn"])
            item={"symbol":"SH600000","ts":ts,
                  **{k:bar[k] for k in ("open","high","low","close")},
                  "volume":bar["volume"]*100,
                  "amount":bar["amount"]}
            original[("SH600000",ts)]=item
        gate=p.overlap_calibrate(code,source,original)
        self.assertEqual(gate["offset_ms"],0)
        self.assertEqual(gate["volume"]["factor"],100.)
        self.assertEqual(gate["amount"]["factor"],1.)
        self.assertGreater(gate["price_fit"],.98)

    def test_private_stage_idempotent_no_external_parquet_write(self):
        day=date(2026,10,14)
        code="600000.SH"
        source=rows(day)
        fake=FakeXtdata(code,source)
        daily={"open":10.,"high":10.01,"low":9.99,
               "close":10.,"volume":100., "amount":10000.}
        expected={day:{code:daily}}
        calib={"SH_OTHER":{"offset_ms":0,"volume":{"factor":100.},
                           "amount":{"factor":1.}}}
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            result,created=p.qmt_stage_stock(code,expected,day,day,calib,folder,fake)
            self.assertTrue(created)
            self.assertEqual(result["rows"],241)
            self.assertTrue(Path(result["private_path"]).is_file())
            self.assertEqual(result["calibrated_volume_factor"],100.)
            self.assertEqual(fake.calls,1)
            reused,created=p.qmt_stage_stock(code,expected,day,day,calib,folder,fake)
            self.assertFalse(created)
            self.assertEqual(fake.calls,1)
            self.assertEqual(reused["sha256"],result["sha256"])
            self.assertFalse(result["market_modified"])

    def test_missing_calibration_allows_source_only_but_no_vendor_conversion(self):
        day=date(2026,10,14)
        code="600000.SH"
        fake=FakeXtdata(code,rows(day))
        expected={day:{code:{"open":10.,"high":10.01,"low":9.99,"close":10.,"volume":24100.,"amount":2410000.}}}
        with tempfile.TemporaryDirectory() as d:
            result,_=p.qmt_stage_stock(code,expected,day,day,{},Path(d),fake)
            self.assertFalse(result["paid_calibration_passed_for_category"])
            self.assertIsNone(result["calibrated_volume_factor"])
            self.assertFalse(result["market_modified"])

    def test_private_calendar_source_hash_tamper_fails(self):
        day=date(2026,10,14);code="600000.SH"
        fake=FakeXtdata(code,rows(day))
        expected={day:{code:{"open":10.,"high":10.01,"low":9.99,"close":10.,"volume":24100.,"amount":2410000.}}}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            receipt,_=p.qmt_stage_stock(code,expected,day,day,{},root,fake)
            with Path(receipt["private_path"]).open("ab") as f:
                f.write(b"corruption")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                p.qmt_stage_stock(code,expected,day,day,{},root,fake)


    def test_private_tdx_day_overlay_fallback_when_physical_month_missing(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from unittest.mock import patch
        day=date(2026,10,14)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for period in p.L.PERIODS:
                (root/"AllCycleAStockData"/period).mkdir(parents=True)
            overlay=root/"private_source_day.parquet"
            records=[{"ts":p.source_day_ts(day),"symbol":"SH"+str(600000+i).zfill(6),
                      "open":10.,"high":10.01,"low":9.99,"close":10.,
                      "volume":1000.,"amount":10000.} for i in range(2500)]
            pq.write_table(pa.Table.from_pylist(records),overlay)
            state={"days":{day.isoformat():{"file":"ignored",
                                           "sha256":p.L.hash_file(overlay)}}}
            with patch.object(p,"read_state",return_value=state),patch.object(
                    p,"checked_path",return_value=overlay):
                clipped=p.latest_certified_day(root,day,day)
                self.assertEqual(clipped,day)
                by_day,stocks,digest,files=p.official_day_universe(root,day,day)
                self.assertEqual(len(by_day[day]),2500)
                self.assertEqual(len(stocks),2500)
                self.assertEqual(files["tdx_overlay"][day.isoformat()],p.L.hash_file(overlay))
                self.assertEqual(len(digest),64)

if __name__=="__main__":
    unittest.main()
