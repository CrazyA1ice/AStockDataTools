"""Synthetic 2026 October 5m→high cycle source-only candidate quality gates."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "synthetic_2026_oct_highcycle_5min_gate",
    HERE.parent/"tools"/"audit-2026-oct-h5-five-minute-high-cycle-candidates-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def fake5(day=M.CANDIDATE,symbol="SH600000",source="h5_only_complete_stockday"):
    rows=[]
    for idx,ts in enumerate(M.grid_timestamps(day)):
        v=10.0+idx/100.0
        rows.append({
            "source_timestamp_ms":ts,
            "symbol":symbol,"period":"5min","trading_date":day.isoformat(),
            "value_source":source,
            "open":v,"high":v+0.3,"low":v-0.2,"close":v+0.1,
            "volume":100.0,"amount":1000.0,
        })
    return rows



def fake1(day=M.CANDIDATE, symbol="SH600000", source="h5_only_complete_stockday"):
    """End-labelled 1m fixtures whose 5m windows reproduce fake5 exactly."""
    result=[]
    for five in fake5(day,symbol):
        for j in range(1,6):
            op=five["open"]
            cl=five["close"] if j==5 else op
            result.append({
                "source_timestamp_ms":five["source_timestamp_ms"]+60000*j,
                "symbol":symbol,"period":"1min",
                "trading_date":day.isoformat(),"value_source":source,
                "open":op,
                "high":five["high"] if j==1 else max(op,cl),
                "low":five["low"] if j==1 else min(op,cl),
                "close":cl,"volume":20.0,"amount":200.0,
            })
    return result


class HighCycleSyntheticSourceGateTests(unittest.TestCase):
    def test_complete_48_start_grid_aggregates_into_16_8_4_1(self):
        rows=fake5()
        for period,want in (("15min",16),("30min",8),("60min",4),("day",1)):
            with self.subTest(period=period):
                actual=M.aggregate_complete_5min(
                    M.CANDIDATE,"SH600000",rows,
                    expected_source="h5_only_complete_stockday",period=period)
                self.assertEqual(len(actual),want)
                self.assertAlmostEqual(
                    sum(x["volume"] for x in actual),48*100.0)
                self.assertAlmostEqual(
                    sum(x["amount"] for x in actual),48*1000.0)
                self.assertEqual(actual[0]["open"],10.0)
                self.assertEqual(actual[-1]["close"],10.57)

    def test_partial_session_refused_and_cannot_be_filled_silently(self):
        with self.assertRaisesRegex(ValueError,"incomplete"):
            M.aggregate_complete_5min(
                M.CANDIDATE,"SH600000",fake5()[:-1],
                expected_source="h5_only_complete_stockday",period="15min")

    def test_bad_clock_grid_and_repeated_keys_rejected(self):
        offgrid=fake5()
        offgrid[0]["source_timestamp_ms"]+=60000
        repeated=fake5()
        # The previous fixture replaced the last row with the *same* last
        # row and accidentally produced a fully valid 48-bar session.
        # Replace it with the penultimate key: one duplicate, one missing.
        repeated[-1]=dict(repeated[-2])
        cases=(("offgrid",offgrid),("duplicate_last_missing",repeated))
        self.assertEqual(len({r["source_timestamp_ms"] for r in offgrid}),48)
        self.assertEqual(len({r["source_timestamp_ms"] for r in repeated}),47)
        for name,rows in cases:
            with self.subTest(case=name):
                with self.assertRaisesRegex(ValueError,"grid|repeated"):
                    M.aggregate_complete_5min(
                        M.CANDIDATE,"SH600000",rows,
                        expected_source="h5_only_complete_stockday",period="30min")

    def test_wrong_provenance_and_security_fails_closed(self):
        for column,value in (("value_source","purchased_parquet"),
                             ("symbol","SZ000001"),
                             ("period","1min"),
                             ("trading_date","2026-10-12")):
            rows=fake5()
            rows[0][column]=value
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError,"provenance"):
                    M.aggregate_complete_5min(
                        M.CANDIDATE,"SH600000",rows,
                        expected_source="h5_only_complete_stockday",period="60min")

    def test_bad_ohlcva_geometry_or_nonfinite_rejected(self):
        for column,value in (("low",12.0),("amount",float("nan")),
                             ("volume",-1.0)):
            rows=fake5()
            rows[1][column]=value
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError,"OHLCVA"):
                    M.aggregate_complete_5min(
                        M.CANDIDATE,"SH600000",rows,
                        expected_source="h5_only_complete_stockday",period="day")

    def test_do_not_invent_week_or_month_using_one_session(self):
        for period in ("week","month"):
            with self.assertRaisesRegex(ValueError,"single-day"):
                M.aggregate_complete_5min(
                    M.CANDIDATE,"SH600000",fake5(),
                    expected_source="h5_only_complete_stockday",period=period)

    def test_purchased_reference_aggregate_numeric_and_raw_labels(self):
        original=fake5(
            M.ANCHOR,source="purchased_parquet")
        for period in M.HIGH:
            derived=M.aggregate_complete_5min(
                M.ANCHOR,"SH600000",original,
                expected_source="purchased_parquet",period=period)
            vendor=[{
                "source_timestamp_ms":item["hypothesized_raw_start_timestamp_ms"],
                "trading_date":item["trading_date"],
                **{f:item[f] for f in M.FIELDS}
            } for item in derived]
            matching=M.compare_purchased_reference(
                M.ANCHOR,period,derived,vendor)
            self.assertEqual(matching["bars_matching_all_six_fields"],len(derived))
            self.assertTrue(matching["full_reference_count_and_keys_agree"])
            vendor[0]["amount"]+=100.0
            discrepant=M.compare_purchased_reference(
                M.ANCHOR,period,derived,vendor)
            self.assertEqual(discrepant["bars_matching_all_six_fields"],len(derived)-1)
            self.assertEqual(discrepant["matching_fields_count"]["amount"],len(derived)-1)
            self.assertEqual(discrepant["matching_fields_count"]["open"],len(derived))

    def test_real_routing_uses_sep_purchased_and_oct_optin_private_only(self):
        observed=[]
        purchased=fake5(M.ANCHOR,source="purchased_parquet")
        private=fake5(M.CANDIDATE,source="h5_only_complete_stockday")
        def fake_query(root,symbol,period,first,last,**kwargs):
            dt=date.fromisoformat(first)
            flag=kwargs.get("allow_verified_private_h5")
            observed.append((period,dt.isoformat(),flag))
            if period=="5min":
                rows=purchased if dt==M.ANCHOR else private
            elif dt==M.ANCHOR:
                derived=M.aggregate_complete_5min(
                    M.ANCHOR,symbol,purchased,
                    expected_source="purchased_parquet",period=period)
                rows=[{
                    "symbol":symbol,"period":period,
                    "source_timestamp_ms":x["hypothesized_raw_start_timestamp_ms"],
                    "trading_date":dt.isoformat(),"value_source":"purchased_parquet",
                    **{f:x[f] for f in M.FIELDS}
                } for x in derived]
            else:
                rows=[]
            by_source={"purchased_parquet" if dt==M.ANCHOR
                       else "verified_private_h5_gap":len(rows)} if rows else {}
            return {
                "bars":rows,
                "safe_summary":{
                    "original_market_files_modified":False,
                    "new_market_or_index_files_written":False,
                    "production_query_activated":False,
                    "matching_bar_count":len(rows),
                    "bars_by_source":by_source
                }
            }
        with patch.object(M.ALL,"query_bars",side_effect=fake_query):
            with patch.object(M.Path,"is_dir",return_value=True):
                output=M.audit(Path("D:/dummy-market"),symbols=("SH600000",))
        self.assertEqual(output["security_count"],1)
        self.assertEqual(len(observed),10)
        self.assertIn(("5min","2026-10-13",True),observed)
        self.assertTrue(all(not enabled for period,_,enabled in observed
                            if period!="5min"))
        self.assertTrue(output["week_month_not_derived_from_single_day"])
        self.assertFalse(output["verified_private_5min_vendor_units_certified"])
        self.assertFalse(output["production_activated"])
        self.assertTrue(output["no_licensed_OHLCVA_values_exported"])
        self.assertNotIn("1000.0",str(output))
        self.assertEqual(output["per_security"][0]
                         ["private_derived_target_day"]["15min"]
                         ["candidate_derived_buckets_when_purchased_absent"],16)


    def test_four_day_october_intraday_sweep_keeps_sha_gated_5min_source_only(self):
        calls=[]
        def only_source(root,symbol,period,day,*,private=False):
            self.assertIsInstance(day,date)  # production _query takes date, not str
            calls.append((symbol,period,day,private))
            if period=="5min":
                self.assertTrue(private)
                return fake5(day,symbol)
            self.assertIn(period,M.INTRADAY)
            self.assertFalse(private)
            return []
        with patch.object(M,"_query",side_effect=only_source):
            with patch.object(M.Path,"is_dir",return_value=True):
                out=M.sweep_verified_october_intraday(
                    Path("D:/synthetic"),
                    symbols=("SH600000","SZ000001"))
        self.assertEqual(out["requested_days"],
                         ["2026-10-08","2026-10-09","2026-10-12","2026-10-13"])
        self.assertEqual(out["security_count"],2)
        self.assertEqual(out["total_candidate_buckets_by_cycle"],
                         {"15min":128,"30min":64,"60min":32})
        self.assertEqual(len(calls),32)
        self.assertTrue(out["daily_candidate_not_certified_or_materialized"])
        self.assertTrue(out["week_month_not_derived"])
        self.assertTrue(out["no_licensed_OHLCVA_values_exported"])
        self.assertFalse(out["new_market_or_index_files_written"])
        self.assertFalse(out["production_activated"])
        self.assertNotIn("1000.0",str(out))

    def test_four_day_sweep_existing_even_partial_purchased_wins(self):
        def source(root,symbol,period,day,*,private=False):
            if period=="5min":
                return fake5(day,symbol)
            if day==date(2026,10,9) and period=="15min":
                return [{"already_purchased_partial":True}]
            return []
        with patch.object(M,"_query",side_effect=source):
            with patch.object(M.Path,"is_dir",return_value=True):
                out=M.sweep_verified_october_intraday(
                    Path("D:/synthetic"),symbols=("SH600000",))
        self.assertEqual(out["total_candidate_buckets_by_cycle"],
                         {"15min":48,"30min":32,"60min":16})
        self.assertEqual(out["purchased_high_cycle_source_blocks"],1)
        blocked=out["per_security"][0]["verified_days"][1]["cycles"]["15min"]
        self.assertEqual(blocked["original_purchased_target_bars"],1)
        self.assertEqual(blocked["candidate_buckets_if_purchased_absent"],0)

    def test_four_day_sweep_missing_h5_receipt_does_not_invent_candidates(self):
        def source(root,symbol,period,day,*,private=False):
            if period=="5min":
                bars=fake5(day,symbol)
                return bars[:-1] if day==date(2026,10,9) else bars
            return []
        with patch.object(M,"_query",side_effect=source):
            with patch.object(M.Path,"is_dir",return_value=True):
                with self.assertRaisesRegex(ValueError,"48-bar"):
                    M.sweep_verified_october_intraday(
                        Path("D:/synthetic"),symbols=("SH600000",))
        with self.assertRaisesRegex(ValueError,"exact four"):
            M.sweep_verified_october_intraday(
                Path("D:/synthetic"),symbols=("SH600000",),
                days=(date(2026,10,13),))


    def test_one_to_five_h5_exact_48_window_conservation(self):
        checked=M.compare_same_h5_one_to_five(
            M.CANDIDATE,"SH600000",fake1(),fake5())
        self.assertEqual(checked["status"],"same_h5_source_diagnostic_only")
        self.assertEqual(checked["source_1min_rows"],240)
        self.assertEqual(checked["complete_5min_windows"],48)
        self.assertEqual(checked["incomplete_5min_windows"],0)
        self.assertEqual(checked["matched_six_field_windows"],48)
        self.assertEqual(checked["matching_fields_count"],{f:48 for f in M.FIELDS})
        self.assertFalse(checked["vendor_physical_units_certified"])
        self.assertTrue(checked["no_licensed_OHLCVA_values_exported"])
        self.assertNotIn("1000.0",str(checked))

    def test_one_to_five_one_missing_minute_excludes_only_own_window(self):
        checked=M.compare_same_h5_one_to_five(
            M.CANDIDATE,"SH600000",fake1()[1:],fake5())
        self.assertEqual(checked["source_1min_rows"],239)
        self.assertEqual(checked["complete_5min_windows"],47)
        self.assertEqual(checked["incomplete_5min_windows"],1)
        self.assertEqual(checked["matched_six_field_windows"],47)

    def test_one_to_five_amount_discrepancy_is_reported_not_normalized(self):
        minute=fake1()
        minute[0]["amount"]+=5.0
        checked=M.compare_same_h5_one_to_five(
            M.CANDIDATE,"SH600000",minute,fake5())
        self.assertEqual(checked["complete_5min_windows"],48)
        self.assertEqual(checked["matched_six_field_windows"],47)
        self.assertEqual(checked["matching_fields_count"]["amount"],47)
        self.assertEqual(checked["matching_fields_count"]["volume"],48)
        self.assertFalse(checked["vendor_physical_units_certified"])

    def test_one_to_five_rejects_duplicate_offgrid_and_broken_ohlcva(self):
        duplicated=fake1()
        duplicated[-1]=dict(duplicated[-2])
        offgrid=fake1()
        offgrid[0]["source_timestamp_ms"]+=30000
        geometry=fake1()
        geometry[0]["high"]=geometry[0]["open"]-1
        for rows in (duplicated,offgrid,geometry):
            with self.subTest(kind=rows[0]["source_timestamp_ms"]):
                with self.assertRaisesRegex(ValueError,"grid|OHLCVA"):
                    M.compare_same_h5_one_to_five(
                        M.CANDIDATE,"SH600000",rows,fake5())

    def test_one_to_five_unavailable_or_purchased_priority_not_comparable(self):
        absent=M.compare_same_h5_one_to_five(
            M.CANDIDATE,"SH600000",[],fake5())
        self.assertEqual(absent["status"],"no_one_minute_source_not_comparable")
        self.assertEqual(absent["complete_5min_windows"],0)
        purchased=fake1(source="purchased_parquet")
        purchased.append(dict(purchased[0]))
        bypass=M.compare_same_h5_one_to_five(
            M.CANDIDATE,"SH600000",purchased,fake5())
        self.assertEqual(bypass["source_1min_rows"],241)
        self.assertEqual(bypass["status"],
                         "purchased_first_one_minute_not_same_h5_source")
        self.assertEqual(bypass["matched_six_field_windows"],0)
        mixed=fake1()
        mixed[0]["value_source"]="purchased_parquet"
        with self.assertRaisesRegex(ValueError,"provenance"):
            M.compare_same_h5_one_to_five(
                M.CANDIDATE,"SH600000",mixed,fake5())

    def test_four_day_one_to_five_diagnostic_is_strictly_opt_in(self):
        queried=[]
        def source(root,symbol,period,day,*,private=False):
            queried.append((period,private))
            if period=="5min":
                return fake5(day,symbol)
            if period=="1min":
                self.assertTrue(private)
                return fake1(day,symbol)[1:]
            return []
        with patch.object(M,"_query",side_effect=source):
            with patch.object(M.Path,"is_dir",return_value=True):
                output=M.sweep_verified_october_intraday(
                    Path("D:/synthetic"),symbols=("SH600000",),
                    check_one_to_five=True)
        self.assertEqual(
            output["total_candidate_buckets_by_cycle"],
            {"15min":64,"30min":32,"60min":16})
        self.assertEqual(sum(period=="1min" for period,_ in queried),4)
        self.assertEqual(len(queried),20)
        self.assertTrue(output["one_to_five_crosscheck_opted_in"])
        self.assertTrue(output["one_to_five_same_vendor_not_independent_certification"])
        for day in output["per_security"][0]["verified_days"]:
            evidence=day["one_to_five_crosscheck"]
            self.assertEqual(evidence["complete_5min_windows"],47)
            self.assertEqual(evidence["matched_six_field_windows"],47)
        self.assertFalse(output["production_activated"])



if __name__=="__main__":
    unittest.main(verbosity=2)
