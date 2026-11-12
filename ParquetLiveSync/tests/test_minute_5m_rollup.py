"""Offline real-price 5m to 15/30/60 minute session OHLCVA rollup checks."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import minute_5m_rollup as R

UTC8=timezone(timedelta(hours=8))
def make(day="2026-11-11",symbol="SH600000"):
    source=[]
    index=0
    for seq in R.GRID:
        for label in seq:
            t=datetime.strptime(day+" "+label,"%Y-%m-%d %H:%M").replace(tzinfo=UTC8)
            p=10.+.03*index
            source.append({
                "ts":int(t.timestamp()*1000),"local_time":label,
                "date":day,"symbol":symbol,
                "open":p,"high":p+.02,"low":p-.01,"close":p+.01,
                "provider_volume":100.+index,"amount_yuan":10000.+10*index})
            index+=1
    return source

class SourceFiveMinuteRollup(unittest.TestCase):
    def test_exact_complete_sh_session_grid(self):
        source=make()
        groups,failed=R.split_complete_5min(source)
        self.assertFalse(failed)
        self.assertEqual(len(groups),1)
        self.assertEqual(len(next(iter(groups.values()))),48)

    def test_all_complete_ohlcva_periods_and_lunch_end_times(self):
        source=make()
        result,failed=R.derive_from_5min(source)
        self.assertFalse(failed)
        self.assertEqual({k:len(v) for k,v in result.items()},
                         {"5min":48,"15min":16,"30min":8,"60min":4})
        self.assertEqual([x["local_time"] for x in result["60min"]],
                         ["10:30","11:30","14:00","15:00"])
        self.assertEqual([x["local_time"] for x in result["30min"]],
                         ["10:00","10:30","11:00","11:30",
                          "13:30","14:00","14:30","15:00"])
        first=result["15min"][0]
        self.assertEqual(first["open"],source[0]["open"])
        self.assertEqual(first["close"],source[2]["close"])
        self.assertEqual(first["high"],max(x["high"] for x in source[:3]))
        self.assertEqual(first["low"],min(x["low"] for x in source[:3]))
        self.assertEqual(first["amount_yuan"],
                         sum(x["amount_yuan"] for x in source[:3]))
        self.assertEqual(first["provider_volume"],
                         sum(x["provider_volume"] for x in source[:3]))

    def test_dropped_five_minute_during_morning_rejects_all_derived_periods(self):
        source=make()
        source.pop(8)
        result,failed=R.derive_from_5min(source)
        self.assertEqual(len(failed),1)
        self.assertEqual({k:len(v) for k,v in result.items()},
                         {k:0 for k in R.PERIODS})

    def test_mismatched_lunch_boundary_never_merged(self):
        source=make()
        source[24]["local_time"]="12:05"
        result,failed=R.derive_from_5min(source)
        self.assertEqual(result["60min"],[])
        self.assertEqual(len(failed),1)

    def test_multiple_stock_day_but_only_full_days_derived(self):
        real=make(symbol="SZ000001")
        incomplete=make(day="2026-11-10",symbol="BJ920021")[:12]
        result,failed=R.derive_from_5min(real+incomplete)
        self.assertEqual(len(failed),1)
        self.assertEqual(len(result["5min"]),48)
        self.assertEqual(len(result["60min"]),4)

    def test_multiple_markets_aggregate_independently(self):
        bars=make(symbol="SH600000")+make(symbol="SZ000001")+make(symbol="BJ920021")
        result,failed=R.derive_from_5min(bars)
        self.assertFalse(failed)
        self.assertEqual(len(result["5min"]),144)
        self.assertEqual(len(result["60min"]),12)
        self.assertEqual({x["symbol"] for x in result["30min"]},
                         {"SH600000","SZ000001","BJ920021"})

if __name__=="__main__":
    unittest.main()
