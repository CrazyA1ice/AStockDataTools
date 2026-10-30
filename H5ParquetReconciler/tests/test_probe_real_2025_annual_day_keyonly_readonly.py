"""Fictional-only 2025 annual Parquet key scan, no commercial market data."""
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
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

SRC=load("keyonly_prior_crossyear_synthetic_fixture",
         HERE/"test_probe_real_h5_parquet_crossyear_day_readonly.py")
D=load("keyonly_2025_annual_proof_under_test",
       HERE.parent/"tools"/"probe-real-2025-annual-day-keyonly-readonly.py")


class AnnualKeyOnlySyntheticTests(TestCase):
    def setUp(self):
        self.f=SRC.CrossyearSyntheticStockDayTests(
            "test_four_crossyear_out_of_sample_stock_days_all_match")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.out=self.f.reports/"annual-keyonly-proof-v1.json"
        guard=patch.object(D.AUDIT,"REPORTS",self.f.reports)
        guard.start()
        self.addCleanup(guard.stop)

    def run_it(self):
        f=self.f
        return D.keyprobe(f.pqroot,f.raw,f.native,f.heldout,self.out)

    def annual(self):
        return self.f.pqroot/"day"/"2025.parquet"

    def target(self):
        return int(datetime(2025,9,30,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)

    def test_realistic_annual_fixture_is_key_only_ready_without_source_values(self):
        original=self.annual().read_bytes()
        report=self.run_it()
        self.assertEqual(report["status"],"ready_for_bounded_price_group_read")
        self.assertEqual(report["source_year_footer_rowgroups"],12)
        self.assertEqual(report["source_year_footer_rows"],24)
        self.assertEqual(report["key_only_rows_scanned"],24)
        self.assertEqual(report["matching_target_key_count"],2)
        self.assertEqual(report["selected_target_rowgroups"],1)
        self.assertEqual(report["selected_target_rowgroup_total_rows"],2)
        self.assertEqual(report["ohlcva_rows_scanned"],0)
        self.assertFalse(report["ohlcva_columns_opened"])
        self.assertFalse(report["raw_h5_or_market_sqlite_opened"])
        self.assertTrue(report["original_source_footer_unchanged"])
        self.assertFalse(report["ready_for_full_market_mirror"])
        self.assertEqual(original,self.annual().read_bytes())
        safe=self.out.read_text(encoding="utf-8")
        for secret in ("SH600000","SZ000001","600000.XSHG","000001.XSHE",
                       "HikyuuData","AllCycleAStockData","202509300000"):
            self.assertNotIn(secret,safe)

    def test_all_twelve_footer_ranges_overlap_but_key_scan_finds_one_target_group(self):
        file=self.annual()
        original=self.f.pq.read_table(file)
        rows=original.to_pylist()
        jan=[r for r in rows if datetime.fromtimestamp(
            r["ts"]/1000,timezone(timedelta(hours=8))).month==1]
        dec=[r for r in rows if datetime.fromtimestamp(
            r["ts"]/1000,timezone(timedelta(hours=8))).month==12]
        targets=[r for r in rows if r["ts"]==self.target()]
        self.assertEqual((len(jan),len(dec),len(targets)),(2,2,2))
        merged=[]
        for group in range(12):
            if group==5:
                merged.extend([jan[0],targets[0],targets[1],dec[0]])
            else:
                merged.extend([jan[0],jan[1],dec[0],dec[1]])
        table=self.f.pa.Table.from_pylist(merged,schema=original.schema)
        self.f.pq.write_table(table,file,row_group_size=4)
        reader=self.f.pq.ParquetFile(file)
        try:
            low,high=D.T.DAY._range_ms("2025-09-30")
            ranges=[reader.metadata.row_group(i).column(0).statistics
                    for i in range(reader.metadata.num_row_groups)]
            self.assertEqual(sum(
                s.min<high and s.max>=low for s in ranges),12)
        finally:
            reader.close()
        report=self.run_it()
        self.assertEqual(report["source_year_footer_rowgroups"],12)
        self.assertEqual(report["key_only_rows_scanned"],48)
        self.assertEqual(report["matching_target_key_count"],2)
        self.assertEqual(report["selected_target_rowgroups"],1)
        self.assertEqual(report["selected_target_rowgroup_total_rows"],4)
        self.assertEqual(report["status"],"ready_for_bounded_price_group_read")

    def test_separate_target_groups_can_be_detected_without_full_ohlcva_read(self):
        file=self.annual()
        table=self.f.pq.read_table(file)
        rows=table.to_pylist()
        t=[row for row in rows if row["ts"]==self.target()]
        untouched=[row for row in rows if row["ts"]!=self.target()]
        # Each target appears in a different 2-row group, while the rest
        # of the calendar remains a valid annual fixture.
        reordered=untouched[:10]+[t[0],untouched[10]]+[
            t[1],untouched[11]]+untouched[12:]
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(reordered,schema=table.schema),
            file,row_group_size=2)
        report=self.run_it()
        self.assertEqual(report["matching_target_key_count"],2)
        self.assertEqual(report["selected_target_rowgroups"],2)
        self.assertEqual(report["selected_target_rowgroup_total_rows"],4)
        self.assertEqual(report["status"],"ready_for_bounded_price_group_read")

    def test_duplicate_target_2025_stock_day_is_blocked_even_cross_group(self):
        file=self.annual()
        table=self.f.pq.read_table(file)
        index=next(i for i,item in enumerate(table["ts"].to_pylist())
                   if item==self.target())
        self.f.pq.write_table(
            self.f.pa.concat_tables([table,table.slice(index,1)]),
            file,row_group_size=2)
        report=self.run_it()
        self.assertEqual(report["status"],"duplicate_target_keys")
        self.assertEqual(report["matching_target_key_count"],3)
        self.assertFalse(report["ready_for_full_market_mirror"])

    def test_missing_target_stock_is_not_replaced_by_another_security(self):
        file=self.annual()
        table=self.f.pq.read_table(file)
        rows=table.to_pylist()
        modified=False
        for row in rows:
            if row["ts"]==self.target() and row["symbol"]=="600000.XSHG":
                row["symbol"]="TEST-OTHER"
                modified=True
        self.assertTrue(modified)
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(rows,schema=table.schema),
            file,row_group_size=2)
        report=self.run_it()
        self.assertEqual(report["status"],"no_target_keys")
        self.assertEqual(report["matching_target_key_count"],1)

    def test_original_150k_price_budget_not_relaxed(self):
        with patch.object(D,"MAX_PRICE_ROWS",1):
            report=self.run_it()
        self.assertEqual(report["status"],"selected_price_rows_exceed_budget")
        self.assertEqual(report["selected_target_rowgroup_total_rows"],2)
        self.assertEqual(report["ohlcva_rows_scanned"],0)

    def test_too_many_target_groups_keeps_two_group_budget(self):
        file=self.annual()
        table=self.f.pq.read_table(file)
        rows=table.to_pylist()
        t=[r for r in rows if r["ts"]==self.target()]
        others=[r for r in rows if r["ts"]!=self.target()]
        shuffled=others[:10]+[t[0],others[10],t[1],others[11]]+others[12:]
        self.f.pq.write_table(
            self.f.pa.Table.from_pylist(shuffled,schema=table.schema),
            file,row_group_size=2)
        with patch.object(D,"MAX_PRICE_GROUPS",1):
            report=self.run_it()
        self.assertEqual(report["status"],"selected_price_group_count_exceeds_budget")
        self.assertEqual(report["selected_target_rowgroups"],2)

    def test_annual_key_footer_budget_refuses_more_than_approved_scan(self):
        with patch.object(D,"MAX_KEY_ROWS",1):
            report=self.run_it()
        self.assertEqual(report["status"],"key_source_invalid")
        self.assertEqual(report["last_phase"],"annual_key_footer_budget")
        self.assertEqual(report["key_only_rows_scanned"],0)

    def test_prior_safe_refused_without_opening_real_annual_source(self):
        original=json.loads(self.f.native.read_text(encoding="utf-8"))
        original["all_two_native_h5_real_daily_records_match"]=False
        self.f.native.write_text(json.dumps(original),encoding="utf-8")
        report=self.run_it()
        self.assertEqual(report["status"],"blocked")
        self.assertEqual(report["last_phase"],"prior_safe_chain")
        self.assertEqual(report["key_only_rows_scanned"],0)

    def test_missing_2025_source_is_a_safe_failure(self):
        self.annual().unlink()
        report=self.run_it()
        self.assertEqual(report["status"],"blocked")
        self.assertEqual(report["last_phase"],"source_file_selection")
        self.assertEqual(report["key_only_rows_scanned"],0)

    def test_existing_or_outside_report_rejected(self):
        self.out.write_text("protected",encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertEqual(self.out.read_text(encoding="utf-8"),"protected")
        other=self.f.root/"outside.json"
        with self.assertRaises(ValueError):
            D.keyprobe(self.f.pqroot,self.f.raw,self.f.native,
                       self.f.heldout,other)
        self.assertFalse(other.exists())

    def test_reader_projects_only_two_keys_no_ohlcva_in_market_scan(self):
        import inspect
        body=inspect.getsource(D.keyprobe)
        self.assertIn('columns=["ts","symbol"]',body)
        self.assertNotIn('DAY._read_bounded_daily(',body)
        self.assertNotIn('PAIR._read_single_h5(',body)
        self.assertNotIn('get_kdata(',body)
        self.assertNotIn('h5py.File(',body)
        self.assertNotIn('write_table(',body)
        self.assertNotIn('sqlite3.connect(',body)


if __name__=="__main__":
    main(verbosity=2)
