"""No licensed market IO: fictional A-share-like day query contracts."""
import importlib.util
import unittest
from datetime import date, datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "combined_private_day_query_test",
    HERE.parent/"tools"/"query-private-combined-day-22274-readonly.py")
Q=importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


def row(day,symbol="SH600000"):
    d=date.fromisoformat(day)
    stamp=int(datetime(d.year,d.month,d.day,tzinfo=Q.MIXED.CORE.UTC8).timestamp()*1000)
    return {"symbol":symbol,"period":"day","trading_date":day,
            "source_timestamp_ms":stamp,"open":10.0,"high":11.0,
            "low":9.0,"close":10.0,"volume":100.0,"amount":1200.0}


def stage_rows():
    keys=[(f"SH600{i:03d}","2026-04-08") for i in range(82)]
    keys.append(("SH600000","2016-09-30"))
    result=[]
    for symbol,day in keys:
        bar=row(day,symbol)
        result.append({"symbol":symbol[2:]+".XSHG",
                       "ts":bar["source_timestamp_ms"],
                       **{k:bar[k] for k in Q.FIELDS},
                       "source":"hikyuu_h5_mixed_day_candidate"})
    return result


class PrivateCombinedQueryTests(unittest.TestCase):
    def merge(self,base=None,whole=None,mixed=None,first="2026-04-07",last="2026-04-09",limit=10):
        return Q.merge_stock_day_rows(
            "SH600000",date.fromisoformat(first),date.fromisoformat(last),
            base or [],whole or [],mixed or [],limit)

    def test_three_nonoverlapping_sources_sorted(self):
        bars,counts=self.merge([row("2026-04-09")],[row("2026-04-07")],[row("2026-04-08")])
        self.assertEqual([b["trading_date"] for b in bars],
                         ["2026-04-07","2026-04-08","2026-04-09"])
        self.assertEqual(sum(counts.values()),3)

    def test_purchased_overlap_with_mixed_rejected(self):
        with self.assertRaisesRegex(ValueError,"overlap"):
            self.merge([row("2026-04-08")],mixed=[row("2026-04-08")])

    def test_purchased_overlap_with_whole_rejected(self):
        with self.assertRaisesRegex(ValueError,"overlap"):
            self.merge([row("2026-04-08")],whole=[row("2026-04-08")])

    def test_private_private_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError,"overlap"):
            self.merge(whole=[row("2026-04-08")],mixed=[row("2026-04-08")])

    def test_repeated_purchased_stockday_different_source_timestamp_rejected(self):
        a=row("2026-04-08")
        b={**a,"source_timestamp_ms":a["source_timestamp_ms"]+60000}
        with self.assertRaisesRegex(ValueError,"overlap"):
            self.merge([a,b])

    def test_wrong_symbol_rejected(self):
        with self.assertRaisesRegex(ValueError,"Noncanonical"):
            self.merge([row("2026-04-08","SH600001")])

    def test_out_of_window_rejected(self):
        with self.assertRaisesRegex(ValueError,"escaped"):
            self.merge([row("2026-04-10")])

    def test_invalid_price_geometry_rejected(self):
        with self.assertRaisesRegex(ValueError,"geometry"):
            self.merge([dict(row("2026-04-08"),high=1.0)])

    def test_timestamp_date_disagreement_rejected(self):
        with self.assertRaisesRegex(ValueError,"mismatch"):
            self.merge([dict(row("2026-04-08"),source_timestamp_ms=0)])

    def test_total_result_budget_enforced(self):
        with self.assertRaisesRegex(ValueError,"max-result-bars"):
            self.merge([row("2026-04-07"),row("2026-04-08")],limit=1)

    def test_selected_private_mixed_exact_83_keys(self):
        bars=Q.selected_mixed_rows(stage_rows(),"SH600000",
                                   date(2026,4,8),date(2026,4,8))
        self.assertEqual(len(bars),1)
        self.assertEqual(bars[0]["trading_date"],"2026-04-08")

    def test_mixed_duplicate_key_rejected(self):
        bars=stage_rows()
        bars[1]=dict(bars[0])
        with self.assertRaisesRegex(ValueError,"duplicate"):
            Q.selected_mixed_rows(bars,"SH600000",date(2026,4,8),date(2026,4,8))

    def test_mixed_stage_missing_record_rejected(self):
        with self.assertRaisesRegex(ValueError,"83"):
            Q.selected_mixed_rows(stage_rows()[:-1],"SH600000",
                                  date(2026,4,8),date(2026,4,8))

    def test_mixed_unverified_source_rejected(self):
        bars=stage_rows()
        bars[0]["source"]="other"
        with self.assertRaisesRegex(ValueError,"Bad/duplicate"):
            Q.selected_mixed_rows(bars,"SH600000",date(2026,4,8),date(2026,4,8))

    def test_mixed_timestamp_not_midnight_rejected(self):
        bars=stage_rows()
        bars[0]["ts"]+=60000
        with self.assertRaisesRegex(ValueError,"local midnight"):
            Q.selected_mixed_rows(bars,"SH600000",date(2026,4,8),date(2026,4,8))


if __name__=="__main__":
    unittest.main(verbosity=2)
