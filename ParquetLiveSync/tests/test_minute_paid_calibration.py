"""Offline real temporary Arrow/Parquet purchased vs Eastmoney minute gate."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import minute_paid_calibration as C
import local_layout as L

CN=timezone(timedelta(hours=8))
def stamp(day,h,m):
    return int(datetime(day.year,day.month,day.day,h,m,tzinfo=CN).timestamp()*1000)

def samples(period,*,price=10.,amount_factor=1.,timestamp_offset=0):
    n={"5min":48,"15min":16,"30min":8,"60min":4}[period]
    step=int(period[:-3])
    symbols=["SH600000","SZ000001"]
    raw=[]
    paid={}
    day=date(2026,9,30)
    for sym in symbols:
        for i in range(n):
            hour=9+((35+step*i)//60)
            minute=(35+step*i)%60
            ts=stamp(day,hour,minute)
            close=price+.01*i
            bar={"symbol":sym,"ts":ts,"open":close,
                 "high":close+.02,"low":close-.02,"close":close,
                 "provider_volume":1000.+i,"amount_yuan":1e6+i*100}
            old={"symbol":sym,"ts":ts+timestamp_offset,
                 "open":close,"high":close+.02,"low":close-.02,
                 "close":close,"volume":(1000.+i)*100,
                 "amount":(1e6+i*100)*amount_factor}
            raw.append(bar)
            paid[(sym,ts+timestamp_offset)]=old
    return raw,paid

class RealPairedMinuteGate(unittest.TestCase):
    def test_four_periods_infer_vendor_shares_and_yuan_from_overlap(self):
        for period in C.PERIODS_OHLCVA:
            incoming,purchased=samples(period)
            proof=C.pair_and_calibrate(period,incoming,purchased)
            self.assertEqual(proof["timestamp_offset_source_to_purchased_ms"],0)
            self.assertEqual(proof["source_volume_to_purchased_factor"],100.)
            self.assertEqual(proof["source_amount_to_purchased_factor"],1.)
            self.assertEqual(proof["symbols_validated"],["SH600000","SZ000001"])
            self.assertTrue(proof["limited_sample_not_full_market_approved"])

    def test_offset_5min_detected_without_guessing(self):
        source,purchased=samples("5min",timestamp_offset=300000)
        # Construct monotonically unique per-bar prices, so shifting the
        # rows mismatches OHLC on every neighboring minute.
        result=C.pair_and_calibrate("5min",source,purchased)
        self.assertEqual(result["timestamp_offset_source_to_purchased_ms"],300000)

    def test_incompatible_amount_units_rejected(self):
        source,purchased=samples("5min",amount_factor=13.)
        with self.assertRaisesRegex(ValueError,"AMOUNT_UNITS_NOT_PROVED"):
            C.pair_and_calibrate("5min",source,purchased)

    def test_incompatible_vendor_prices_rejected(self):
        source,purchased=samples("5min")
        for row in purchased.values():
            for col in ("open","high","low","close"):
                row[col]+=5
        with self.assertRaisesRegex(ValueError,"PRICE_OR_TIME_UNVERIFIED"):
            C.pair_and_calibrate("5min",source,purchased)

    def test_not_enough_paid_bars_rejected(self):
        source,purchased=samples("60min")
        purchased={k:v for i,(k,v) in enumerate(purchased.items()) if i<3}
        with self.assertRaisesRegex(ValueError,"PRICE_OR_TIME_UNVERIFIED"):
            C.pair_and_calibrate("60min",source,purchased)

    def test_actual_arrow_parquet_purchased_month_and_sha_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"stock"
            for period in L.PERIODS:
                (root/"AllCycleAStockData"/period).mkdir(parents=True)
            incoming,purchased=samples("5min")
            schema=pa.schema([
                ("ts",pa.int64()),("symbol",pa.string()),
                *( (k,pa.float64()) for k in
                   ("open","high","low","close","volume","amount"))])
            path=root/"AllCycleAStockData"/"5min"/"2026-09.parquet"
            pq.write_table(pa.Table.from_pylist(list(purchased.values()),
                                                schema=schema),path)
            original,read_path,sha=C.source_day_rows(
                root,"5min",date(2026,9,30),["SH600000","SZ000001"])
            self.assertEqual(read_path,path)
            self.assertEqual(sha,L.hash_file(path))
            self.assertEqual(len(original),len(purchased))
            self.assertEqual(
                C.pair_and_calibrate("5min",incoming,original)[
                    "source_volume_to_purchased_factor"],100.)

    def test_never_calibrate_trend_as_full_1min_ohlcva(self):
        with self.assertRaisesRegex(ValueError,"Never calibrate"):
            C.pair_and_calibrate("1min",[],{})

if __name__=="__main__":
    unittest.main()
