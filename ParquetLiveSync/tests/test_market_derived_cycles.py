"""Synthetic offline regression for all-cycle QMT minute rollups/scheduler.

NO real QMT downloads, HTTP or original physical stock market modifications.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
import local_layout as L
import live_sync as LIVE
import market_month_storage as S
import market_derived_cycles as D
import market_all_cycles as A

DATA_DAY=date(2026, 9, 30)


def minute_rows(symbol="SH600000",day=DATA_DAY,*,offset_ms=0,auction=False):
    base=datetime(day.year,day.month,day.day,tzinfo=L.UTC8)
    rows=[]
    for k,minute in enumerate(D.BASE_CLOCK):
        stamp=base.replace(hour=minute//60,minute=minute%60)
        price=10.+k*.0005
        vol=200. + (50. if auction and k==0 else 0.)
        rows.append({"ts":int(stamp.timestamp()*1000)+offset_ms,
                     "symbol":symbol,
                     "open":price,"high":price+.04,"low":price-.05,
                     "close":price+.01,
                     "volume":vol,"amount":vol*(price+.01)})
    return rows


class HigherMinuteTests(unittest.TestCase):
    def test_all_four_periods_have_exact_daily_time_grid_and_session_break(self):
        bars=minute_rows(auction=True)
        for period,n in D.BARS.items():
            with self.subTest(period=period):
                made=D.aggregate_stock_day(
                    bars,period,one_minute_offset_ms=0)
                self.assertEqual(len(made),240//n)
                self.assertEqual(made[0]["open"],bars[0]["open"])
                self.assertEqual(made[0]["volume"],
                                 sum(x["volume"] for x in bars[:n]))
                self.assertEqual(made[-1]["close"],bars[-1]["close"])
                self.assertEqual(made[n and 120//n]["open"],
                                 bars[120]["open"])
                self.assertAlmostEqual(
                    sum(x["amount"] for x in made),
                    sum(x["amount"] for x in bars),places=4)
                stamp=datetime.fromtimestamp(made[0]["ts"]/1000,L.UTC8)
                # Normalize the expected clock across the hour boundary:
                # 09:30 + 30 minutes is 10:00, never 09:60.
                first_end=9*60+30+n
                self.assertEqual((stamp.hour,stamp.minute),
                                 divmod(first_end,60))
                midday=datetime.fromtimestamp(
                    made[120//n]["ts"]/1000,L.UTC8)
                self.assertEqual(midday.strftime("%H:%M"),
                                 f"{13+(n//60):02}:{n%60:02}")

    def test_subminute_source_grid_drift_is_rejected_for_every_period(self):
        clean=minute_rows()
        for period in D.PERIODS:
            for delta_ms in (1, 45000, 59999):
                with self.subTest(period=period, delta_ms=delta_ms):
                    modified=clean.copy()
                    modified[12]={**modified[12],
                                  "ts":modified[12]["ts"]+delta_ms}
                    with self.assertRaisesRegex(ValueError, "off-minute"):
                        D.aggregate_stock_day(
                            modified,period,one_minute_offset_ms=0)
        shifted=minute_rows(offset_ms=60000)
        # A whole-minute vendor offset is calibrated and still supported.
        self.assertEqual(len(D.aggregate_stock_day(
            shifted,"30min",one_minute_offset_ms=60000)),8)

    def test_reject_unverified_minute_label_offsets(self):
        clean=minute_rows()
        with self.assertRaisesRegex(ValueError,"grid offset"):
            D.aggregate_stock_day(
                clean,"5min",one_minute_offset_ms=45000)
        with self.assertRaisesRegex(ValueError,"timestamp shift"):
            D.aggregate_stock_day(
                clean,"5min",one_minute_offset_ms=0,
                period_label_shift_ms=45000)

    def test_paid_one_minute_vendor_offset_and_scale(self):
        rows=minute_rows(offset_ms=60000)
        for period in D.PERIODS:
            result=D.aggregate_stock_day(
                rows,period,one_minute_offset_ms=60000,
                period_label_shift_ms=-60000,volume_factor=.01,
                amount_factor=100.)
            self.assertEqual(result[0]["ts"],rows[D.BARS[period]-1]["ts"]-60000)
            self.assertAlmostEqual(result[0]["volume"],
                                   sum(r["volume"] for r in rows[:D.BARS[period]])*.01)

    def test_missing_or_duplicate_minute_is_rejected(self):
        rows=minute_rows()
        with self.assertRaisesRegex(ValueError,"INCOMPLETE"):
            D.aggregate_stock_day(rows[:-1],"5min",one_minute_offset_ms=0)
        corrupt=rows.copy()
        corrupt[1]={**corrupt[1],"ts":corrupt[0]["ts"]}
        with self.assertRaisesRegex(ValueError,"timestamp"):
            D.aggregate_stock_day(corrupt,"60min",one_minute_offset_ms=0)
        broken=rows.copy()
        broken[12]={**broken[12],"ts":broken[12]["ts"]+45000}
        with self.assertRaisesRegex(ValueError,"grid"):
            D.aggregate_stock_day(broken,"15min",one_minute_offset_ms=0)

    def test_actual_purchased_period_time_and_unit_inference(self):
        sources={}
        original={}
        gates={"providers":{"SH_OTHER":{"category":"SH_OTHER","offset_ms":0,
                                           "volume":{"factor":1},"amount":{"factor":1}},
                            "SZ":{"category":"SZ","offset_ms":0,
                                  "volume":{"factor":1},"amount":{"factor":1}},
                            "STAR":{"category":"STAR","offset_ms":0,
                                    "volume":{"factor":1},"amount":{"factor":1}}}}
        for symbol in ("SH600000","SZ000001","SH688001"):
            source=minute_rows(symbol)
            sources[symbol]=source
            derived=D.aggregate_stock_day(
                source,"30min",one_minute_offset_ms=0,
                period_label_shift_ms=60000,volume_factor=.01,amount_factor=10)
            for bar in derived:
                original[(symbol,bar["ts"])]=bar
        rules=D._infer_one("30min",original,sources,gates)
        self.assertEqual(rules["timestamp_shift_from_1min_last_ms"],60000)
        self.assertAlmostEqual(rules["volume_factor"],.01)
        self.assertAlmostEqual(rules["amount_factor"],10.)
        self.assertGreaterEqual(rules["price_match"],.99)

    def test_purchased_anchor_collector_retains_239_without_creating_bar(self):
        original={}
        for sym in ("SH600000","SZ000001","SH688001"):
            records=minute_rows(sym)
            for row in records[1:]:
                original[(sym,row["ts"])]=row
        accepted=D._collect_anchor_minutes(original,{})
        self.assertEqual(set(accepted),
                         {"SH600000","SZ000001","SH688001"})
        self.assertEqual({sym:len(rows) for sym,rows in accepted.items()},
                         {sym:239 for sym in accepted})
        for sym in accepted:
            self.assertNotIn(
                minute_rows(sym)[0]["ts"],
                {row["ts"] for row in accepted[sym]})

    def test_real_241_purchased_auction_folds_without_dropping_value(self):
        for auction_volume in (0., 450.):
            for period,n in D.BARS.items():
                with self.subTest(period=period,auction=auction_volume):
                    full=minute_rows()
                    auction={**full[0],
                             "ts":full[0]["ts"]-60000,
                             "open":9.91,"high":10.08,"low":9.88,
                             "close":10.,"volume":auction_volume,
                             "amount":auction_volume*10.}
                    paid=[auction]+full
                    self.assertEqual(len(paid),241)
                    observed=D._anchor_complete_buckets(
                        paid,period,one_minute_offset_ms=0)
                    folded,_=D.S._fold_241_day(
                        paid,0,"2026-09")
                    expected=D.aggregate_stock_day(
                        folded,period,one_minute_offset_ms=0)
                    self.assertEqual(observed,expected)
                    self.assertEqual(len(observed),240//n)
                    self.assertAlmostEqual(
                        sum(x["volume"] for x in observed),
                        sum(x["volume"] for x in paid),places=6)
                    self.assertAlmostEqual(
                        sum(x["amount"] for x in observed),
                        sum(x["amount"] for x in paid),places=4)
                    if auction_volume:
                        self.assertEqual(observed[0]["open"],auction["open"])
                        self.assertGreaterEqual(observed[0]["high"],
                                                auction["high"])
                        self.assertLessEqual(observed[0]["low"],
                                             auction["low"])

    def test_real_241_auction_rejects_invalid_source_without_faking_bars(self):
        full=minute_rows()
        auction={**full[0],"ts":full[0]["ts"]-60000,
                 "volume":200.,"amount":2000.}
        paid=[auction]+full
        with self.assertRaisesRegex(ValueError,"sub-minute timestamp drift"):
            invalid=paid.copy()
            invalid[0]={**invalid[0],"ts":invalid[0]["ts"]+45000}
            D._anchor_complete_buckets(
                invalid,"15min",one_minute_offset_ms=0)
        with self.assertRaisesRegex(ValueError,"unpaired volume/amount"):
            invalid=paid.copy()
            invalid[0]={**invalid[0],"amount":0.}
            D._anchor_complete_buckets(
                invalid,"5min",one_minute_offset_ms=0)
        with self.assertRaisesRegex(ValueError,"241-minute grid"):
            invalid=paid.copy()
            invalid[1]={**invalid[1],"ts":invalid[1]["ts"]+60000}
            D._anchor_complete_buckets(
                invalid,"5min",one_minute_offset_ms=0)

    def test_three_real_241_anchor_categories_are_not_preemptively_excluded(self):
        original={}
        for symbol in ("SH600000","SH688001","SZ000001"):
            data=minute_rows(symbol)
            auction={**data[0],"ts":data[0]["ts"]-60000,
                     "volume":0.,"amount":0.}
            for row in [auction]+data:
                original[(symbol,row["ts"])]=row
        collected=D._collect_anchor_minutes(original,{})
        self.assertEqual(set(collected),{"SH600000","SH688001","SZ000001"})
        self.assertTrue(all(len(rows)==241 for rows in collected.values()))
        for sym,rows in collected.items():
            for period in D.PERIODS:
                with self.subTest(symbol=sym,period=period):
                    buckets=D._anchor_complete_buckets(
                        rows,period,one_minute_offset_ms=0)
                    self.assertEqual(len(buckets),240//D.BARS[period])

    def test_paid_241_anchors_infer_all_four_periods_from_actual_auction(self):
        prices={}
        purchased={}
        sealed={"providers":{
            "SH_OTHER":{"category":"SH_OTHER","offset_ms":0,
                        "volume":{"factor":1},"amount":{"factor":1}},
            "SZ":{"category":"SZ","offset_ms":0,
                  "volume":{"factor":1},"amount":{"factor":1}},
            "STAR":{"category":"STAR","offset_ms":0,
                    "volume":{"factor":1},"amount":{"factor":1}}}}
        for symbol in ("SH600000","SH688001","SZ000001"):
            day=minute_rows(symbol)
            auction={**day[0],"ts":day[0]["ts"]-60000,
                     "open":9.95,"high":10.07,"low":9.93,
                     "close":10.,"volume":310.,"amount":3100.}
            purchased[symbol]=[auction]+day
            normalized,_=D.S._fold_241_day(purchased[symbol],0,"2026-09")
            prices[symbol]=normalized
        for period in D.PERIODS:
            with self.subTest(period=period):
                purchased_higher={}
                for symbol,values in prices.items():
                    derived=D.aggregate_stock_day(
                        values,period,one_minute_offset_ms=0,
                        period_label_shift_ms=60000,
                        volume_factor=.01,amount_factor=10.)
                    for row in derived:
                        purchased_higher[(symbol,row["ts"])]=row
                matched=D._infer_one(period,purchased_higher,purchased,sealed)
                self.assertEqual(
                    matched["timestamp_shift_from_1min_last_ms"],60000)
                self.assertAlmostEqual(matched["volume_factor"],.01)
                self.assertAlmostEqual(matched["amount_factor"],10.)
                self.assertGreater(matched["price_match"],.99)

    def test_239_purchased_minute_anchor_calibrates_complete_windows_only(self):
        # Legitimate purchased 239-minute days may lack a single label.
        # Missing minutes must not be synthesized or published.
        complete=minute_rows("SH600000")
        incomplete=complete[1:]
        for period,n in D.BARS.items():
            with self.subTest(period=period):
                partial=D._anchor_complete_buckets(
                    incomplete,period,one_minute_offset_ms=0)
                self.assertEqual(len(partial),240//n-1)
                all_buckets=D.aggregate_stock_day(
                    complete,period,one_minute_offset_ms=0)
                self.assertEqual(partial,all_buckets[1:])
                with self.assertRaisesRegex(ValueError,"INCOMPLETE"):
                    D.aggregate_stock_day(
                        incomplete,period,one_minute_offset_ms=0)

    def test_238_purchased_anchor_can_prove_only_genuine_buckets(self):
        full=minute_rows()
        partial=[row for i,row in enumerate(full) if i not in (0,140)]
        for period,n in D.BARS.items():
            with self.subTest(period=period):
                actual=D._anchor_complete_buckets(
                    partial,period,one_minute_offset_ms=0)
                self.assertEqual(len(actual),240//n-2)
        with self.assertRaisesRegex(ValueError,"238-241 genuine minute bars"):
            D._anchor_complete_buckets(
                partial[:-1],"5min",one_minute_offset_ms=0)

    def test_partial_purchased_anchor_infers_real_high_cycle_time_and_units(self):
        full={sym:minute_rows(sym) for sym in
              ("SH600000","SZ000001","SH688001")}
        partial={sym:records[1:] for sym,records in full.items()}
        sealed={"providers":{
            "SH_OTHER":{"category":"SH_OTHER","offset_ms":0,
                        "volume":{"factor":1},"amount":{"factor":1}},
            "SZ":{"category":"SZ","offset_ms":0,
                  "volume":{"factor":1},"amount":{"factor":1}},
            "STAR":{"category":"STAR","offset_ms":0,
                    "volume":{"factor":1},"amount":{"factor":1}}}}
        for period in D.PERIODS:
            with self.subTest(period=period):
                original={}
                for sym,records in full.items():
                    for row in D.aggregate_stock_day(
                            records,period,one_minute_offset_ms=0,
                            period_label_shift_ms=60000,
                            volume_factor=.01,amount_factor=10):
                        original[(sym,row["ts"])]=row
                rules=D._infer_one(period,original,partial,sealed)
                self.assertEqual(
                    rules["timestamp_shift_from_1min_last_ms"],60000)
                self.assertAlmostEqual(rules["volume_factor"],.01)
                self.assertAlmostEqual(rules["amount_factor"],10.)
                self.assertGreater(rules["price_match"],.99)

    def test_partial_anchor_does_not_floor_off_grid_or_assume_unknown_bars(self):
        for missing in (0,120):
            source=minute_rows()
            source.pop(missing)
            corrupted=source.copy()
            corrupted[1]={**corrupted[1],
                          "ts":corrupted[1]["ts"]+45000}
            with self.assertRaisesRegex(ValueError,
                                        "sub-minute timestamp drift"):
                D._anchor_complete_buckets(
                    corrupted,"15min",one_minute_offset_ms=0)
        with self.assertRaisesRegex(ValueError,
                                    "Unverified purchased source minute offset"):
            D._anchor_complete_buckets(
                minute_rows(),"5min",one_minute_offset_ms=45000)

    def test_calibration_rejects_wrong_ohlc_and_inconsistent_units(self):
        sources={sym:minute_rows(sym) for sym in ("SH600000","SZ000001")}
        sealed={"providers":{
            "SH_OTHER":{"category":"SH_OTHER","offset_ms":0,
                        "volume":{"factor":1},"amount":{"factor":1}},
            "SZ":{"category":"SZ","offset_ms":0,
                   "volume":{"factor":1},"amount":{"factor":1}}}}
        original={}
        for symbol,rows in sources.items():
            for i,bar in enumerate(D.aggregate_stock_day(
                    rows,"5min",one_minute_offset_ms=0)):
                original[(symbol,bar["ts"])]={
                    **bar,"close":bar["close"]+5.,"amount":bar["amount"]*(i+1)}
        with self.assertRaisesRegex(ValueError,"OHLC mismatch"):
            D._infer_one("5min",original,sources,sealed)

    def test_streaming_candidate_rowgroups_bounded_and_zero_legacy_forgery(self):
        with tempfile.TemporaryDirectory() as tmp:
            month="2026-11"
            day=date(2026,11,13)
            original=minute_rows("SH600000",day)
            additional=minute_rows("SZ000001",day)
            raw=pa.Table.from_pylist(original+additional,schema=S.SCHEMA)
            src=Path(tmp)/"original_1m.parquet"
            pq.write_table(raw,src,row_group_size=139)
            rules={p:{"timestamp_shift_from_1min_last_ms":0,
                      "volume_factor":1.,"amount_factor":1.}
                   for p in D.PERIODS}
            with patch.object(D.B,"_calibration",
                              return_value={"offset_ms":0}):
                derived,partial=D._derive_from_source(
                    src,{str(day)},rules,{},workspace=Path(tmp),
                    month=month,progress=lambda _:None)
            self.assertEqual(partial,{})
            for period in D.PERIODS:
                with self.subTest(period=period):
                    expected=2*240//D.BARS[period]
                    self.assertEqual(derived[period]["rows"],expected)
                    file=pq.ParquetFile(derived[period]["path"])
                    try:
                        self.assertEqual(file.metadata.num_rows,expected)
                    finally:
                        file.close()

    def test_first_four_period_commit_then_second_run_is_idempotent(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"stock"
            for period in L.PERIODS:
                (root/"AllCycleAStockData"/period).mkdir(parents=True)
            day=date(2026,11,13)
            label="2026-11"
            table=pa.Table.from_pylist(
                minute_rows("SH600000",day)+minute_rows("SZ000001",day),
                schema=S.SCHEMA)
            original=root/"AllCycleAStockData"/"1min"/(label+".parquet")
            pq.write_table(table,original,row_group_size=139)
            source_sha=L.hash_file(original)
            fake_state={"periods":{"1min":{label:{
                "sha256":source_sha,"days":[str(day)]}}},
                "qmt_calibration_sha256":"a"*64}
            rules={p:{"timestamp_shift_from_1min_last_ms":0,
                      "volume_factor":1.,"amount_factor":1.}
                   for p in D.PERIODS}
            with (patch.object(D.S,"state_for",return_value=fake_state),
                  patch.object(D,"paid_rules",return_value=rules),
                  patch.object(D,"_sealed_calibration",return_value={}),
                  patch.object(D.B,"_calibration",
                               return_value={"offset_ms":0}),
                  patch.object(D.LIVE,"exclusive_writer",
                               return_value=contextlib.nullcontext())):
                work=Path(tmp)/"work"
                first=D.run(root,apply=True,workspace=work,progress=lambda _:None)
                self.assertEqual(len(first),4)
                self.assertTrue(all(x["status"]=="COMMITTED" for x in first))
                digests={}
                for period,n in D.BARS.items():
                    target=root/"AllCycleAStockData"/period/(label+".parquet")
                    frame=pq.read_table(target)
                    self.assertEqual(frame.num_rows,2*240//n)
                    digests[period]=L.hash_file(target)
                repeated=D.run(root,apply=True,workspace=work,
                               progress=lambda _:None)
                self.assertEqual(repeated,[])
                for period in D.PERIODS:
                    target=root/"AllCycleAStockData"/period/(label+".parquet")
                    self.assertEqual(L.hash_file(target),digests[period])

    def test_week_month_calibration_caches_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"stock"
            for cycle in L.PERIODS:
                (root/"AllCycleAStockData"/cycle).mkdir(parents=True)
            for cycle in ("day","week","month"):
                for year,mon in A.MONTHS:
                    (root/"AllCycleAStockData"/cycle/
                     f"{year}-{mon:02}.parquet").write_bytes(b"vendor-original")
            work=Path(tmp)/"work"
            rules={"week":{"period":"week","rule":"friday",
                           "intraday_offset_ms":0},
                   "month":{"period":"month","rule":"last_traded",
                            "intraday_offset_ms":0}}
            with patch.object(A.R,"audit_one",
                              side_effect=lambda root,p:rules[p]) as audit:
                got=A.week_month_rules(root,workspace=work,logger=lambda _:None)
                got2=A.week_month_rules(root,workspace=work,logger=lambda _:None)
                self.assertEqual(audit.call_count,2)
                self.assertEqual(got,got2)
            (root/"AllCycleAStockData"/"week"/"2026-08.parquet").write_bytes(
                b"other-source!")
            with self.assertRaisesRegex(ValueError,"source changed"):
                A.week_month_rules(root,workspace=work,logger=lambda _:None)

    def test_trading_calendar_handles_qmt_ms_and_yyyymmdd(self):
        import types
        import sys
        first=date(2026,10,13)
        stamp=int(datetime(2026,10,14,tzinfo=L.UTC8).timestamp()*1000)
        fake=types.ModuleType("xtquant")
        fake.xtdata=types.SimpleNamespace(get_trading_dates=lambda *args,**kw:
                                          ["20261013",stamp])
        with patch.dict(sys.modules,{"xtquant":fake}):
            result=A.verified_qmt_trading_calendar(date(2026,10,15))
        self.assertEqual(result,{first,date(2026,10,14)})

    def test_trading_calendar_rejects_weekend_or_no_entries(self):
        import types
        import sys
        fake=types.ModuleType("xtquant")
        fake.xtdata=types.SimpleNamespace(get_trading_dates=lambda *args,**kw:
                                          ["20261017"])
        with patch.dict(sys.modules,{"xtquant":fake}):
            with self.assertRaisesRegex(ValueError,"invalid date"):
                A.verified_qmt_trading_calendar(date(2026,10,18))
        fake.xtdata.get_trading_dates=lambda *args,**kw:[]
        with patch.dict(sys.modules,{"xtquant":fake}):
            with self.assertRaisesRegex(ValueError,"unavailable"):
                A.verified_qmt_trading_calendar(date(2026,10,18))

    def test_orchestration_reports_incomplete_phase_not_false_eight_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"stock"
            for period in L.PERIODS:
                (root/"AllCycleAStockData"/period).mkdir(parents=True)
            with (patch.object(A.U,"update",return_value=[{"status":"DONE"}]),
                  patch.object(A.D,"run",side_effect=ValueError("UNKNOWN_PERIOD_UNIT")),
                  patch.object(A.R,"run",return_value={"commits":[]}),
                  patch.object(A,"verified_qmt_trading_calendar",
                               return_value={date(2026,11,13)}),
                  patch.object(A,"week_month_rules",return_value={
                    "week":{"rule":"friday","intraday_offset_ms":0},
                    "month":{"rule":"last_traded","intraday_offset_ms":0}})):
                with self.assertRaisesRegex(RuntimeError,"5_15_30_60MIN"):
                    A.run(root,mode="auto",apply=True,logger=lambda _:None)


if __name__=="__main__":
    unittest.main()
