"""Offline source-independent T+1 crosscheck contracts. No QMT or HTTP required."""
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_1m_crosscheck",HERE/"qmt_1m_crosscheck.py")
C=importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def sample(day=date(2026,11,12),code="600000.SH"):
    rows=[]
    for h,m in sorted(C.P.GRID):
        stamp=datetime(day.year,day.month,day.day,h,m,tzinfo=C.P.CN).isoformat()
        rows.append({"datetime_cn":stamp,"symbol":code,
                     "open":10.0,"high":10.03,"low":9.98,"close":10.02,
                     "volume":100.,"amount":1002.})
    return rows


class IndependentCrossSourceTests(unittest.TestCase):
    def test_aggregate_241_into_48_without_fabricating_minutes(self):
        source=sample()
        for flag in (True,False):
            result=C.qmt_aggregate_5m(source,include_auction=flag)
            self.assertEqual(len(result),48)
            self.assertEqual(datetime.fromtimestamp(result[0]["ts"]/1000,C.P.CN).strftime("%H:%M"),"09:35")
            self.assertEqual(datetime.fromtimestamp(result[-1]["ts"]/1000,C.P.CN).strftime("%H:%M"),"15:00")
            self.assertEqual(result[0]["volume"],600. if flag else 500.)
        with self.assertRaisesRegex(ValueError,"241"):
            C.qmt_aggregate_5m(source[:-1],include_auction=True)

    def test_exact_ohlc_comparison_preserves_unmatched_windows(self):
        source=[{"ts":1,"open":10.,"high":11.,"low":9.,"close":10.5},
                {"ts":2,"open":10.,"high":11.,"low":9.,"close":10.5}]
        external=[{"ts":1,"open":10.,"high":11.,"low":9.,"close":10.5},
                  {"ts":3,"open":12.,"high":12.,"low":12.,"close":12.}]
        evidence=C.intersect_compare(source,external)
        self.assertEqual(evidence["overlap_bars"],1)
        self.assertEqual(evidence["qmt_only_bars"],1)
        self.assertEqual(evidence["external_only_bars"],1)
        self.assertEqual(evidence["ohlc"]["close"]["matching"],1)

    def test_native_volume_factor_is_diagnostic_only(self):
        q=[{"ts":x,"volume":2000.} for x in range(10)]
        source=[{"ts":x,"provider_volume":20.} for x in range(10)]
        stats=C.volume_fit(q,source,source_field="provider_volume")
        self.assertEqual(stats["best_factor_external_to_QMT"],100.)
        self.assertEqual(stats["status"],"DIAGNOSTIC_NOT_PRODUCTION_UNITS")

    def test_t1_revision_explicitly_detects_changed_amount(self):
        rows=sample()
        old={C.P.stamp_ms(x["datetime_cn"]):{**x,"ts":C.P.stamp_ms(x["datetime_cn"])}
             for x in rows}
        self.assertEqual(C.revision_check(old,rows)["status"],"SAME_AS_PRIOR_PRIVATE_SNAPSHOT")
        modified=[dict(x) for x in rows]
        modified[0]["amount"]+=30.
        result=C.revision_check(old,modified)
        self.assertEqual(result["status"],"QMT_T1_REVISION_DETECTED")
        self.assertEqual(result["changed_minutes"],1)

    def test_tencent_320_limit_no_amount_not_promoted(self):
        day=date(2026,11,12)
        records=[["202611120930","10.00","10.02","10.03","9.98","100","","3"]]
        data={"data":{"sh600000":{"m1":records}}}
        raw=json.dumps(data).encode()
        with tempfile.TemporaryDirectory() as temp:
            rows,evidence=C.fetch_tencent("SH600000",day,Path(temp),
                                          fetcher=lambda url:raw)
            self.assertEqual(evidence["target_bars"],1)
            self.assertEqual(rows[0]["source_volume"],100.)
            self.assertNotIn("amount",rows[0])
            self.assertTrue(Path(evidence["private_file"]).exists())

    def test_eastmoney_5m_parses_independent_ohlcva(self):
        day=date(2026,11,12)
        raw=json.dumps({"rc":0,"data":{"code":"600000","klines":[
            "2026-11-12 09:35,10.0,10.1,10.2,9.9,100,10100,0"]}}).encode()
        with tempfile.TemporaryDirectory() as temp:
            rows,evidence=C.fetch_eastmoney_5m("SH600000",day,Path(temp),
                requester=lambda url:(raw,json.loads(raw)))
            self.assertEqual(evidence["target_bars"],1)
            self.assertEqual(rows[0]["amount_yuan"],10100.)

    def test_day_guard_blocks_live_current_day(self):
        from unittest.mock import patch
        with patch.object(C.R,"load_bound_context",side_effect=AssertionError("must not inspect files")):
            with self.assertRaisesRegex(ValueError,"COMPLETED"):
                C.run("D:/stock",day=date(9999,1,1),xtdata=object())

if __name__=="__main__":
    unittest.main()
