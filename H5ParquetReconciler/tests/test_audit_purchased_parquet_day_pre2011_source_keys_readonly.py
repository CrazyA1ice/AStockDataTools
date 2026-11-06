"""All-fictional Parquet day pre-2011 physical source-key audit tests."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "purchased_pre2011_day_physical_footer_key_tests",
    HERE.parent/"tools"/"audit-purchased-parquet-day-pre2011-source-keys-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
UTC8=timezone(timedelta(hours=8))


def stamp(label,hour=8):
    y,m,d=[int(part) for part in label.split("-")]
    return int(datetime(y,m,d,hour,tzinfo=UTC8).timestamp()*1000)


class PurchasedPre2011SourceKeyAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.day=self.root/"AllCycleAStockData"/"day"
        self.day.mkdir(parents=True)

    def make(self,name, rows, *, stats=True):
        path=self.day/name
        path.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.table({
            "ts":pa.array([ts for ts,_ in rows],type=pa.int64()),
            "symbol":pa.array([symbol for _,symbol in rows],type=pa.string()),
        }),path,write_statistics=stats,row_group_size=2)
        return path

    def test_2011_plus_purchased_day_footer_proves_no_early_history(self):
        p=self.make("2026/2026-10.parquet", [
            (stamp("2026-10-09"),"600000.XSHG"),
            (stamp("2026-10-12"),"000001.XSHE")])
        before=(p.stat().st_size,p.stat().st_mtime_ns)
        res=M.audit(self.root)
        self.assertEqual(res["source_files"],1)
        self.assertEqual(res["rowgroups_pruned_proven_by_min_ts_ge_2011"],1)
        self.assertEqual(res["physical_rows_key_projected"],0)
        self.assertTrue(res["no_1990_2010_purchased_keys_in_audited_files"])
        self.assertTrue(res["all_rowgroups_have_trusted_min_ts_ge_2011"])
        self.assertFalse(res["h5_stockday_key_overlap_ever_compared"])
        self.assertFalse(res["historical_candidate_staged_or_merged"])
        self.assertFalse(res["market_files_written"])
        self.assertTrue(res["source_key_only_no_ohlcva_read"])
        self.assertEqual(before,(p.stat().st_size,p.stat().st_mtime_ns))

    def test_misnamed_parquet_with_old_1990_2010_keys_cannot_be_pruned(self):
        self.make("2099-year-file.parquet",[
            (stamp("1990-12-20"),"600000.XSHG"),
            (stamp("2010-12-31"),"000001.XSHE")])
        res=M.audit(self.root)
        self.assertEqual(res["purchased_1990_2010_a_share_code_candidate_stockdays"],2)
        self.assertEqual(res["purchased_1990_2010_all_stockday_keys"],2)
        self.assertEqual(res["rowgroups_key_projected"],1)
        self.assertFalse(res["no_1990_2010_purchased_keys_in_audited_files"])
        self.assertEqual(sum(y["purchased_a_share_code_candidate_stockdays"]
                             for y in res["annual_coverage"]),2)
        self.assertNotIn("SH600000",json.dumps(res))

    def test_no_footer_stats_forces_physical_key_projection(self):
        self.make("late-data-no-stats.parquet",[
            (stamp("2026-10-12"),"600000.XSHG")],stats=False)
        res=M.audit(self.root)
        self.assertEqual(res["rowgroups_missing_or_untrusted_timestamp_footer"],1)
        self.assertEqual(res["physical_rows_key_projected"],1)
        self.assertFalse(res["all_rowgroups_have_trusted_min_ts_ge_2011"])

    def test_reversed_source_schema_order_still_uses_named_ts(self):
        pq.write_table(pa.table({
            "symbol":pa.array(["600000.XSHG"],type=pa.string()),
            "ts":pa.array([stamp("1993-06-01")],type=pa.int64()),
        }),self.day/"reversed-order.parquet")
        result=M.audit(self.root)
        self.assertEqual(result["purchased_1990_2010_a_share_code_candidate_stockdays"],1)
        self.assertFalse(result["no_1990_2010_purchased_keys_in_audited_files"])

    def test_null_source_timestamps_are_not_silently_skipped(self):
        pq.write_table(pa.table({
            "ts":pa.array([None,stamp("2026-10-09")],type=pa.int64()),
            "symbol":pa.array(["600000.XSHG","600000.XSHG"],type=pa.string()),
        }),self.day/"nullable.parquet",write_statistics=False)
        with self.assertRaisesRegex(ValueError,"Null purchased day timestamp"):
            M.audit(self.root)

    def test_other_instrument_classified_separately(self):
        self.make("1991.parquet",[
            (stamp("1991-01-02"),"000001.XSHG"),
            (stamp("1991-01-03"),"900901.XSHG")])
        res=M.audit(self.root)
        self.assertEqual(res["purchased_1990_2010_other_instrument_stockdays"],2)
        self.assertEqual(res["purchased_1990_2010_a_share_code_candidate_stockdays"],0)
        self.assertEqual(res["annual_coverage"][1]["purchased_distinct_native_date_labels"],2)

    def test_exact_duplicate_symbol_day_across_files_rejected(self):
        original=(stamp("2009-06-01"),"600000.XSHG")
        self.make("old-2009-a.parquet",[original])
        self.make("old-2009-b.parquet",[original])
        with self.assertRaisesRegex(ValueError,"Duplicated purchased pre-2011"):
            M.audit(self.root)

    def test_day_early_source_scan_budget_blocks_before_reading_values(self):
        self.make("old.parquet",[
            (stamp("2009-06-01"),"600000.XSHG"),
            (stamp("2009-06-02"),"600000.XSHG")])
        with self.assertRaisesRegex(ValueError,"projection budget"):
            M.audit(self.root,max_projected_rows=1)

    def test_pre1990_rows_are_flagged_not_claimed_inside_inventory(self):
        self.make("old.parquet",[
            (stamp("1989-12-29"),"600000.XSHG"),
            (stamp("1990-12-20"),"600000.XSHG")])
        out=M.audit(self.root)
        self.assertEqual(out["pre1990_physical_rows_detected"],1)
        self.assertEqual(out["purchased_1990_2010_all_stockday_keys"],1)

    def test_missing_purchased_day_files_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"No purchased day files"):
            M.audit(self.root)

    def test_unexpected_nonparquet_artifact_fails_closed(self):
        (self.day/"unknown.txt").write_text("unexpected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"non-Parquet"):
            M.audit(self.root)

    def test_symlink_source_rejected_without_windows_symlink_privilege(self):
        self.make("2026.parquet",[(stamp("2026-10-12"),"600000.XSHG")])
        original=Path.is_symlink
        with patch.object(Path,"is_symlink",lambda p: p.name=="2026.parquet" or original(p)):
            with self.assertRaisesRegex(ValueError,"Symlinked purchased day"):
                M.audit(self.root)

    def test_noninteger_ts_column_rejected(self):
        path=self.day/"bad.parquet"
        pq.write_table(pa.table({
            "ts":pa.array([float(stamp("2009-06-02"))],type=pa.float64()),
            "symbol":pa.array(["600000.XSHG"])}),path)
        with self.assertRaisesRegex(ValueError,"original integer"):
            M.audit(self.root)

    def test_foreign_symbol_with_pre2011_physical_key_rejected(self):
        self.make("old.parquet",[(stamp("2008-06-02"),"not-a-listed-code")])
        with self.assertRaisesRegex(ValueError,"Unknown original purchased day security code"):
            M.audit(self.root)


if __name__=="__main__":
    unittest.main(verbosity=2)
