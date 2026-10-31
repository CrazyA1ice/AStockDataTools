"""Pure synthetic cross-year daily H5/Parquet factor evidence safety tests."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "fixed_stratified_daily_factor_under_test",
    HERE.parent/"tools"/"probe-private-day-overlap-stratified-factors-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def good():
    raw={
        "datetime":202408190000,
        "openPrice":10000,"highPrice":11000,
        "lowPrice":9000,"closePrice":10500,
        "transCount":1500,"transAmount":2500,
    }
    purchased={"open":10.0,"high":11.0,"low":9.0,"close":10.5,
               "volume":150000.0,"amount":2500000.0}
    return purchased,raw


def successful_evaluation():
    p,h=good()
    return M.evaluate_stockday(p,h)


class StratifiedFactorTests(unittest.TestCase):
    def test_fixed_years_and_dates_do_not_reuse_old_evidence(self):
        selected=M.checked_calendar()
        self.assertEqual(len(selected),8)
        self.assertEqual(sorted(M.SAMPLES),[2016,2020,2024,2026])
        self.assertNotIn("2026-09-30",selected)
        self.assertNotIn("2026-08-24",selected)

    def test_exact_raw_integer_candidate_conversion_matches(self):
        d=successful_evaluation()
        self.assertTrue(all(d["price_tolerance_hits"].values()))
        self.assertTrue(all(d["quantity_positive_pairs"].values()))
        self.assertTrue(all(d["quantity_factor_hits"].values()))

    def test_price_mismatch_is_not_silently_normalized(self):
        p,h=good()
        p["close"]=10.52
        result=M.evaluate_stockday(p,h)
        self.assertFalse(result["price_tolerance_hits"]["close"])
        self.assertTrue(result["quantity_factor_hits"]["amount"])

    def test_volume_mismatch_is_reported_not_promoted(self):
        p,h=good()
        p["volume"]=151000.0
        result=M.evaluate_stockday(p,h)
        self.assertFalse(result["quantity_factor_hits"]["volume"])
        self.assertTrue(result["quantity_factor_hits"]["amount"])

    def test_amount_mismatch_is_reported_not_promoted(self):
        p,h=good()
        p["amount"]=2600000.0
        result=M.evaluate_stockday(p,h)
        self.assertFalse(result["quantity_factor_hits"]["amount"])

    def test_zero_volume_is_non_evidence(self):
        p,h=good()
        p["volume"]=0.0
        h["transCount"]=0
        r=M.evaluate_stockday(p,h)
        self.assertFalse(r["quantity_positive_pairs"]["volume"])
        self.assertFalse(r["quantity_factor_hits"]["volume"])

    def test_nan_parquet_value_rejected(self):
        p,h=good()
        p["amount"]=float("nan")
        with self.assertRaisesRegex(ValueError,"Nonfinite"):
            M.evaluate_stockday(p,h)

    def test_negative_h5_integer_rejected(self):
        p,h=good()
        h["transAmount"]=-1
        with self.assertRaisesRegex(ValueError,"Nonfinite"):
            M.evaluate_stockday(p,h)

    def test_inverted_ohlc_geometry_rejected(self):
        p,h=good()
        p["high"]=9.9
        with self.assertRaisesRegex(ValueError,"geometry"):
            M.evaluate_stockday(p,h)

    def test_four_year_aggregate_counts_and_mismatch_flag(self):
        d=successful_evaluation()
        samples={year:[d]*4 for year in M.SAMPLES}
        s=M.summarize(samples)
        self.assertEqual(s["2020"]["paired_stockdays"],4)
        self.assertEqual(s["2016"]["price_field_within_0p005"]["open"],4)
        self.assertTrue(all(x["all_sampled_numeric_candidates_match"] for x in s.values()))
        bad={**d,"quantity_factor_hits":{**d["quantity_factor_hits"],"amount":False}}
        samples[2024]=[d,d,bad,d]
        s=M.summarize(samples)
        self.assertEqual(s["2024"]["candidate_factor_hit_pairs"]["amount"],3)
        self.assertFalse(s["2024"]["all_sampled_numeric_candidates_match"])
        self.assertTrue(s["2016"]["all_sampled_numeric_candidates_match"])

    def test_reject_undercounted_incomplete_samples(self):
        d=successful_evaluation()
        data={year:[d]*4 for year in M.SAMPLES}
        data[2016]=data[2016][:3]
        with self.assertRaisesRegex(ValueError,"both stocks"):
            M.summarize(data)

    def test_reject_false_positive_quantity_factor_when_pair_is_zero(self):
        d=successful_evaluation()
        bad={**d,
             "quantity_positive_pairs":{"amount":False,"volume":True},
             "quantity_factor_hits":{"amount":True,"volume":True}}
        data={year:[d]*4 for year in M.SAMPLES}
        data[2020]=[d,d,d,bad]
        with self.assertRaisesRegex(ValueError,"contradictory"):
            M.summarize(data)

    def test_safe_path_must_be_new_within_module_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports=Path(tmp)/"reports"
            reports.mkdir()
            outside=Path(tmp)/"outside.json"
            existing=reports/"taken.json"
            existing.write_text("{}")
            with patch.object(M,"REPORTS",reports):
                self.assertEqual(M.new_safe(reports/"new.json"),reports/"new.json")
                with self.assertRaisesRegex(ValueError,"NEW"):
                    M.new_safe(outside)
                with self.assertRaisesRegex(ValueError,"NEW"):
                    M.new_safe(existing)

    def test_readonly_run_emits_aggregate_only_not_production_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports=Path(tmp)/"reports"
            reports.mkdir()
            root=Path(tmp)/"source"
            root.mkdir()
            for market in ("sh","sz"):
                (root/"HikyuuData").mkdir(exist_ok=True)
                (root/"HikyuuData"/(market+"_day.h5")).write_bytes(b"fictional")
            data,raw=good()
            def fake_pq(_root,year):
                paired={(s,day):dict(data)
                        for day in M.SAMPLES[year] for s in M.SYMBOLS}
                return paired,1234,2
            version={"ready_for_production_query":False,
                     "candidate_total_new_stockday_rows":22274,
                     "whole_day_candidate_rows":22191,
                     "mixed_stockday_candidate_rows":83}
            out=reports/"aggregate.json"
            with patch.object(M,"REPORTS",reports),\
                 patch.object(M.REG,"LOCK",root/"not-a-lock"),\
                 patch.object(M.REG,"load_version",return_value=version),\
                 patch.object(M,"source_snapshot",return_value=(("fixed",10,10),)),\
                 patch.object(M,"scan_purchased_year",side_effect=fake_pq),\
                 patch.object(M.PAIR,"_read_single_h5",return_value=raw):
                report=M.run(root,"e"*64,out)
            self.assertEqual(report["total_distinct_stockdays_compared"],16)
            self.assertTrue(report["all_16_samples_numerically_within_candidate_tolerances"])
            self.assertFalse(report["candidate_source_units_certified"])
            self.assertFalse(report["ready_for_automatic_market_merge"])
            self.assertFalse(report["ready_for_production_query"])
            self.assertTrue(report["source_file_stat_is_not_cryptographic_content_proof"])
            txt=out.read_text(encoding="utf-8")
            self.assertNotIn("SH600000",txt)
            self.assertNotIn("SZ000001",txt)
            self.assertNotIn("transAmount",txt)
            self.assertNotIn(str(root),txt)

    def test_source_changed_refuses_safe_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports=Path(tmp)/"reports";reports.mkdir()
            root=Path(tmp)/"source";root.mkdir()
            out=reports/"no.json"
            version={"ready_for_production_query":False,
                     "candidate_total_new_stockday_rows":22274,
                     "whole_day_candidate_rows":22191,
                     "mixed_stockday_candidate_rows":83}
            p,raw=good()
            def fake_pq(_root,year):
                return {(s,d):dict(p) for d in M.SAMPLES[year] for s in M.SYMBOLS},20,1
            with patch.object(M,"REPORTS",reports),\
                 patch.object(M.REG,"LOCK",root/"not-a-lock"),\
                 patch.object(M.REG,"load_version",return_value=version),\
                 patch.object(M,"source_snapshot",side_effect=[(("a",1,1),),(("a",2,2),)]),\
                 patch.object(M,"scan_purchased_year",side_effect=fake_pq),\
                 patch.object(M.PAIR,"_read_single_h5",return_value=raw):
                with self.assertRaisesRegex(ValueError,"changed"):
                    M.run(root,"f"*64,out)
            self.assertFalse(out.exists())

    def test_exact_purchased_year_stockdays_bounded_without_raw_export(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"purchased.parquet"
            dates=M.SAMPLES[2026]
            records=[]
            for d in dates:
                ts=int(datetime.fromisoformat(d+"T00:00:00+08:00").timestamp()*1000)
                for symbol in M.SYMBOLS:
                    p,_=good()
                    records.append({"ts":ts,"symbol":symbol,**p})
            t=pa.Table.from_pylist(records)
            pq.write_table(t,source,row_group_size=1)
            with patch.object(M.CORE,"year_files",return_value=[source]):
                found,scanned,groups=M.scan_purchased_year(root,2026)
            self.assertEqual(len(found),4)
            self.assertEqual(scanned,4)
            self.assertEqual(groups,4)

    def test_purchased_nonfloat64_ohlcva_rejected_before_comparison(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"purchased.parquet"
            records=[]
            for d in M.SAMPLES[2026]:
                ts=int(datetime.fromisoformat(
                    d+"T00:00:00+08:00").timestamp()*1000)
                for symbol in M.SYMBOLS:
                    p,_=good()
                    records.append({"ts":ts,"symbol":symbol,**p})
            table=pa.Table.from_pylist(records)
            # A rounded Arrow float32 price is not valid evidence for
            # the original purchased float64 conversion hypothesis.
            index=table.schema.get_field_index("close")
            table=table.set_column(index,"close",
                table["close"].cast(pa.float32()))
            pq.write_table(table,source)
            with patch.object(M.CORE,"year_files",return_value=[source]):
                with self.assertRaisesRegex(ValueError,"dtypes"):
                    M.scan_purchased_year(root,2026)

    def test_duplicate_purchased_stockday_key_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"purchased.parquet"
            rows=[]
            for day in M.SAMPLES[2026]:
                for symbol in M.SYMBOLS:
                    p,_=good()
                    rows.append({"ts":int(datetime.fromisoformat(
                        day+"T00:00:00+08:00").timestamp()*1000),"symbol":symbol,**p})
            pq.write_table(pa.Table.from_pylist(rows+[rows[0]]),source)
            with patch.object(M.CORE,"year_files",return_value=[source]):
                with self.assertRaisesRegex(ValueError,"Duplicate original"):
                    M.scan_purchased_year(root,2026)


if __name__=="__main__":
    unittest.main(verbosity=2)
