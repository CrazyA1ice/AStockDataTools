"""Only synthetic Parquet/H5: key-located 2025 + monthly 2026 day proof."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest import TestCase,main
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SRC=load("crossyear_keyloc_synthetic_2025_fixture",
         HERE/"test_probe_real_h5_parquet_crossyear_day_readonly.py")
T=load("crossyear_keylocated_main",
       HERE.parent/"tools"/"probe-real-h5-parquet-crossyear-day-readonly.py")
K=load("crossyear_keylocated_prior_keyproof",
       HERE.parent/"tools"/"probe-real-2025-annual-day-keyonly-readonly.py")


class KeyLocatedAnnualAndMonthlyTests(TestCase):
    def setUp(self):
        self.f=SRC.CrossyearSyntheticStockDayTests(
            "test_four_crossyear_out_of_sample_stock_days_all_match")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        for obj in (T.AUDIT,K.AUDIT):
            p=patch.object(obj,"REPORTS",self.f.reports)
            p.start();self.addCleanup(p.stop)
        self.key=self.f.reports/"synthetic-key-only.json"
        self.out=self.f.reports/"synthetic-crossyear-v2.json"
        self.rebuild_key()

    def rebuild_key(self):
        if self.key.exists():
            self.key.unlink()
        result=K.keyprobe(self.f.pqroot,self.f.raw,self.f.native,
                          self.f.heldout,self.key)
        return result

    def run_it(self):
        f=self.f
        return T.run(f.pqroot,f.h5root,f.raw,f.native,f.heldout,
                     self.out,annual_key_only_safe=self.key)

    def target(self):
        return int(datetime(2025,9,30,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)

    def test_two_date_four_stock_days_match_with_key_revalidation(self):
        report=self.run_it()
        self.assertEqual(report["crossyear_aggregate"]["stock_days_compared"],4)
        self.assertEqual(
            report["crossyear_aggregate"]["volume_candidate_raw_h5_times100_matched"],4)
        self.assertEqual(
            report["crossyear_aggregate"]["amount_candidate_raw_h5_times1000_matched"],4)
        self.assertEqual(report["crossyear_aggregate"]["per_field_price_tolerance_matches"],
                         {"open":4,"high":4,"low":4,"close":4})
        self.assertEqual(report["source_parquet_layouts"],
                         {"2025":"annual_two_column_key_revalidated","2026":"monthly"})
        self.assertTrue(report["annual_2025_prior_key_only_safe_revalidated"])
        self.assertEqual(report["annual_2025_key_only_rows_rechecked"],24)
        self.assertEqual(report["annual_2025_ohlcva_rows_scanned"],2)
        self.assertEqual(report["source_parquet_total_rows_scanned"],4)
        self.assertEqual(report["annual_2025_selected_rowgroups_scanned"],1)
        self.assertIn("annual_2025_key_only",report["previous_safe_sha256"])
        self.assertFalse(report["licensed_parquet_to_h5_mapping_certified"])
        self.assertFalse(report["ready_for_full_market_mirror"])
        safe=self.out.read_text(encoding="utf-8")
        for forbidden in ("SH600000","SZ000001","HikyuuData",
                          "AllCycleAStockData","000001.XSHE","600000.XSHG",
                          "202509300000"):
            self.assertNotIn(forbidden,safe)

    def test_12_footer_groups_overlap_target_but_keyloc_only_reads_one(self):
        file=self.f.pqroot/"day"/"2025.parquet"
        table=self.f.pq.read_table(file)
        rows=table.to_pylist()
        jan=[r for r in rows if datetime.fromtimestamp(
            r["ts"]/1000,timezone(timedelta(hours=8))).month==1]
        dec=[r for r in rows if datetime.fromtimestamp(
            r["ts"]/1000,timezone(timedelta(hours=8))).month==12]
        targets=[r for r in rows if r["ts"]==self.target()]
        self.assertEqual((len(jan),len(dec),len(targets)),(2,2,2))
        expanded=[]
        for i in range(12):
            expanded.extend(
                [jan[0],targets[0],targets[1],dec[0]] if i==5
                else [jan[0],jan[1],dec[0],dec[1]])
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(expanded,schema=table.schema),
            file,row_group_size=4)
        prior=self.rebuild_key()
        self.assertEqual(prior["source_year_footer_rowgroups"],12)
        self.assertEqual(prior["selected_target_rowgroups"],1)
        self.assertEqual(prior["key_only_rows_scanned"],48)
        with self.assertRaisesRegex(ValueError,
                                    "Cannot safely inspect bounded annual"):
            self.f.run_it() # footer-only original path intentionally blocked
        report=self.run_it()
        self.assertEqual(report["annual_2025_key_only_rows_rechecked"],48)
        self.assertEqual(report["annual_2025_selected_rowgroups_scanned"],1)
        self.assertEqual(report["annual_2025_ohlcva_rows_scanned"],4)
        self.assertEqual(report["crossyear_aggregate"]["stock_days_compared"],4)

    def test_invalid_prior_keyonly_status_rejected_before_any_price_scan(self):
        data=json.loads(self.key.read_text(encoding="utf-8"))
        for key,val in (("status","duplicate_target_keys"),
                        ("matching_target_key_count",1),
                        ("ohlcva_columns_opened",True),
                        ("ready_for_full_market_mirror",True)):
            with self.subTest(key=key):
                altered=dict(data);altered[key]=val
                self.key.write_text(json.dumps(altered),encoding="utf-8")
                try:
                    with self.assertRaisesRegex(
                            ValueError,"key-only prior SAFE not qualified"):
                        self.run_it()
                    self.assertFalse(self.out.exists())
                finally:
                    self.key.write_text(json.dumps(data),encoding="utf-8")
        self.assertEqual(self.run_it()["annual_2025_key_only_rows_rechecked"],24)

    def test_recheck_detects_changed_target_key_even_with_same_footer_rows(self):
        annual=self.f.pqroot/"day"/"2025.parquet"
        data=self.f.pq.read_table(annual)
        rows=data.to_pylist()
        idx=next(i for i,r in enumerate(rows)
                 if r["ts"]==self.target() and r["symbol"]=="600000.XSHG")
        rows[idx]["symbol"]="UNRELATED"
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(rows,schema=data.schema),
            annual,row_group_size=2)
        with self.assertRaisesRegex(ValueError,
                                    "Cannot safely inspect key-located annual"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_recheck_detects_duplicate_target_replacing_old_unrelated_key(self):
        annual=self.f.pqroot/"day"/"2025.parquet"
        data=self.f.pq.read_table(annual)
        rows=data.to_pylist()
        january=next(i for i,r in enumerate(rows)
                     if r["ts"]!=self.target())
        rows[january]["ts"]=self.target()
        rows[january]["symbol"]="600000.XSHG"
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(rows,schema=data.schema),
            annual,row_group_size=2)
        with self.assertRaisesRegex(ValueError,
                                    "Cannot safely inspect key-located annual"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_annual_150k_ohlcva_budget_remains_hard(self):
        with patch.object(T,"MAX_YEAR_READ_ROWS",1):
            with self.assertRaisesRegex(
                    ValueError,"Cannot safely inspect key-located annual"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_2026_monthly_amount_discrepancy_is_still_reported(self):
        # Do not rebuild 2025 prior key SAFE; only mutate the other month's
        # Parquet float so that the new crossyear run sees a mismatch.
        path=self.f.pqroot/"day"/"2026-08.parquet"
        data=self.f.pq.read_table(path)
        rows=data.to_pylist()
        rows[0]["amount"]*=1.5
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(rows,schema=data.schema),path,
            row_group_size=2)
        report=self.run_it()
        self.assertEqual(
            report["crossyear_aggregate"]["amount_candidate_raw_h5_times1000_matched"],3)
        self.assertEqual(report["per_sample_day"]["2026-08-24"]
                         ["candidate_amount_raw_h5_times1000_matched"],1)
        self.assertFalse(report["ready_for_full_market_mirror"])

    def test_preexisting_or_outside_output_rejected(self):
        self.out.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.out.read_text(encoding="utf-8"),"protected")
        away=self.f.root/"outside.json"
        with self.assertRaises(ValueError):
            T.run(self.f.pqroot,self.f.h5root,self.f.raw,self.f.native,
                  self.f.heldout,away,annual_key_only_safe=self.key)

    def test_key_scan_restricted_to_two_columns_and_price_to_target_groups(self):
        import inspect
        body=inspect.getsource(T.read_annual_2025_keylocated_day)
        self.assertIn('columns=["ts","symbol"]',body)
        self.assertIn('row_groups=selected,columns=list(DAY.NEEDED)',body)
        self.assertIn("MAX_YEAR_READ_ROWS",body)
        self.assertNotIn("sqlite3.connect(",body)
        self.assertNotIn("h5py.File(",body)
        self.assertNotIn("write_table(",body)


if __name__=="__main__":
    main(verbosity=2)
