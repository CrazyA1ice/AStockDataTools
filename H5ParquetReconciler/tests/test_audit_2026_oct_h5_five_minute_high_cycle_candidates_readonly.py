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


if __name__=="__main__":
    unittest.main(verbosity=2)
