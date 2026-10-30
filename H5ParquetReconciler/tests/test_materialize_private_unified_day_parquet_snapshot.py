"""Synthetic-only immutable Parquet-first private daily snapshot tests."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "private_unified_daily_materializer",
    HERE.parent/"tools"/"materialize-private-unified-day-parquet-snapshot.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

SHA="a"*64
SOURCE_DATA_ROOT_NAME="fictional_market"


def stamp(d):
    return int(datetime(2026,10 if d==8 else 9,d,
                        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)


def day_bar(sym,d,source,price):
    return {
        "symbol":sym,"period":"day",
        "trading_date":f"2026-{10 if d==8 else 9:02d}-{d:02d}",
        "source_timestamp_ms":stamp(d),
        "value_source":source,
        "open":float(price),"high":float(price+.2),
        "low":float(price-.2),"close":float(price+.1),
        "volume":1300.0,"amount":150000.25,
    }


def baseline():
    owned=day_bar("SH600000",30,"purchased_parquet",10.1)
    extra=day_bar("SH600000",8,"private_hikyuu_h5_gap_candidate",10.2)
    summary={
        "format":M.BATCH.FORMAT,
        "private_version_sha256":SHA,
        "from_date":"2026-09-30",
        "to_date":"2026-10-08",
        "purchased_parquet_priority":True,
        "private_overlay_stages_sha_and_keys_verified":True,
        "selected_private_stages_final_snapshot_reverified":True,
        "no_source_market_writes":True,
        "no_production_query_switch":True,
        "no_raw_ohlcva_in_safe_summary":True,
        "no_active_pointer_read_or_change":True,
        "private_version_selection_mode":"explicit_immutable_version_sha256",
        "symbol_count":2,
        "symbols":["SH600000","SZ000001"],
        "matching_bar_count":2,
        "purchased_parquet_bars_returned":1,
        "private_overlay_bars_returned":1,
        "per_symbol_counts":{
            "SH600000":{"purchased_bars":1,"private_bars":1,"returned_bars":2},
            "SZ000001":{"purchased_bars":0,"private_bars":0,"returned_bars":0},
        },
    }
    return {"bars_by_symbol":{"SH600000":[owned,extra],"SZ000001":[]},
            "safe_summary":summary}


class PrivateMaterializedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/"H5ParquetReconciler"
        self.root=Path(self.tmp.name)/SOURCE_DATA_ROOT_NAME
        self.root.mkdir()
        self.work=self.base/"work"
        self.snaps=self.work/"unified_parquet"/"snapshots"
        self.reports=self.base/"reports"
        self.snaps.mkdir(parents=True)
        self.reports.mkdir()
        self.folder=self.snaps/"snapshot_abcdef012345"
        self.safe=self.reports/"private-summary.json"
        self.source=baseline()
        for obj,key,value in (
            (M,"MODULE",self.base),
            (M,"WORK",self.work),
            (M,"SNAPSHOTS",self.snaps),
            (M,"REPORTS",self.reports)):
            p=patch.object(obj,key,value)
            p.start()
            self.addCleanup(p.stop)
        self.mock=patch.object(M.BATCH,"query_private_day_overlay_batch",
                               return_value=self.source)
        self.mock_call=self.mock.start()
        self.addCleanup(self.mock.stop)

    def run_it(self):
        return M.materialize(
            self.root,["SH600000","SZ000001"],
            "2026-09-30","2026-10-08",SHA,self.folder,self.safe)

    def test_fictional_purchased_first_parquet_materializes_and_roundtrips(self):
        import pyarrow.parquet as pq
        safe=self.run_it()
        self.assertEqual(safe["row_count"],2)
        self.assertEqual(safe["purchased_rows"],1)
        self.assertEqual(safe["h5_gap_candidate_rows"],1)
        self.assertFalse(safe["ready_for_full_market_mirror"])
        file=self.folder/"day.parquet"
        rows=pq.read_table(file).to_pylist()
        self.assertEqual([r["trading_date"] for r in rows],
                         ["2026-09-30","2026-10-08"])
        self.assertEqual([r["value_source"] for r in rows],
                         ["purchased_parquet","private_hikyuu_h5_gap_candidate"])
        self.assertEqual(rows[0]["amount"],150000.25)
        manifest=json.loads((self.folder/"manifest.json").read_text())
        self.assertEqual(manifest["private_parquet_sha256"],M.hash_file(file))
        self.assertTrue(manifest["all_written_values_roundtrip_exactly"])
        self.assertEqual(self.safe.exists(),True)
        self.assertEqual(safe["manifest_sha256"],
                         M.hash_file(self.folder/"manifest.json"))
        self.assertEqual(
            self.mock_call.call_args.kwargs["use_private_active"],False)
        self.assertFalse((self.work/"unified_parquet"/"active-day-overlay.json").exists())
        self.assertFalse((self.root/"day").exists())
        for forbidden in ("150000.25","HikyuuData",SOURCE_DATA_ROOT_NAME,
                          '"open"','"amount"'):
            self.assertNotIn(forbidden,self.safe.read_text(encoding="utf-8"))

    def test_existing_snapshot_and_safe_are_never_overwritten(self):
        self.folder.mkdir()
        with self.assertRaisesRegex(ValueError,"NEW direct"):
            self.run_it()
        self.mock_call.assert_not_called()
        self.folder.rmdir()
        self.safe.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW JSON"):
            self.run_it()
        self.assertEqual(self.safe.read_text(),"protected")
        self.mock_call.assert_not_called()

    def test_private_snapshot_path_outside_module_or_wrong_name_rejected(self):
        for folder in (self.base/"foo",self.snaps/"snapshot_bad",
                       self.snaps/"snapshot_abcdef012345"/"subdir",
                       self.root/"snapshot_abcdef012345"):
            with self.subTest(folder=folder):
                with self.assertRaises(ValueError):
                    M.safe_paths(folder,self.safe)
        self.mock_call.assert_not_called()

    def test_duplicate_purchased_private_stock_day_rejected_without_outputs(self):
        rows=self.source["bars_by_symbol"]["SH600000"]
        rows[1]["trading_date"]=rows[0]["trading_date"]
        with self.assertRaisesRegex(ValueError,"duplicate stock-day"):
            self.run_it()
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.safe.exists())

    def test_invalid_source_and_nonfinite_ohlc_rejected_before_write(self):
        row=self.source["bars_by_symbol"]["SH600000"][1]
        row["value_source"]="unverified_unknown"
        with self.assertRaisesRegex(ValueError,"untrusted source"):
            self.run_it()
        self.assertFalse(self.folder.exists())
        row["value_source"]="private_hikyuu_h5_gap_candidate"
        row["open"]=float("nan")
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            self.run_it()
        self.assertFalse(self.folder.exists())

    def test_query_failure_cannot_leave_private_snapshot_or_safe_report(self):
        self.mock_call.side_effect=ValueError("purchased source overlap changed")
        with self.assertRaisesRegex(ValueError,"source overlap"):
            self.run_it()
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.safe.exists())

    def test_query_provenance_and_count_tampering_rejected(self):
        for field,value in (("purchased_parquet_priority",False),
                            ("no_production_query_switch",False),
                            ("selected_private_stages_final_snapshot_reverified",False),
                            ("matching_bar_count",3),
                            ("private_overlay_bars_returned",2),
                            ("private_version_sha256","0"*64),
                            ("no_active_pointer_read_or_change",False)):
            with self.subTest(field=field):
                cloned=baseline()
                cloned["safe_summary"][field]=value
                with self.assertRaises(ValueError):
                    M.normalize_rows(cloned,SHA,["SH600000","SZ000001"],"2026-09-30","2026-10-08")
        self.assertFalse(self.folder.exists())

    def test_invalid_schema_roundtrip_prevents_safe_report(self):
        import pyarrow.parquet as pq
        original=pq.read_table
        def corrupted(*args,**kwargs):
            result=original(*args,**kwargs)
            return result.slice(0,1)
        with patch.object(pq,"read_table",side_effect=corrupted):
            with self.assertRaisesRegex(ValueError,"exactly roundtrip"):
                self.run_it()
        self.assertTrue((self.folder/"day.parquet").is_file())
        self.assertFalse(self.safe.exists())

    def test_out_of_window_bar_and_wrong_requested_symbol_list_rejected(self):
        cloned=baseline()
        cloned["bars_by_symbol"]["SH600000"][1]["trading_date"]="2026-10-09"
        with self.assertRaisesRegex(ValueError,"out-of-window"):
            M.normalize_rows(cloned,SHA,["SH600000","SZ000001"],"2026-09-30","2026-10-08")
        cloned=baseline()
        with self.assertRaises(ValueError):
            M.normalize_rows(cloned,SHA,["SZ000001","SH600000"],"2026-09-30","2026-10-08")

    def test_zero_rows_refused_and_no_untrusted_bool_numeric(self):
        s=baseline()
        s["bars_by_symbol"]={"SH600000":[],"SZ000001":[]}
        s["safe_summary"]["matching_bar_count"]=0
        s["safe_summary"]["purchased_parquet_bars_returned"]=0
        s["safe_summary"]["private_overlay_bars_returned"]=0
        s["safe_summary"]["per_symbol_counts"]={
            k:{"purchased_bars":0,"private_bars":0,"returned_bars":0}
            for k in ("SH600000","SZ000001")}
        with self.assertRaisesRegex(ValueError,"Bounded row accounting"):
            M.normalize_rows(s,SHA,["SH600000","SZ000001"],"2026-09-30","2026-10-08")
        self.source["bars_by_symbol"]["SH600000"][0]["volume"]=True
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            self.run_it()


if __name__=="__main__":
    unittest.main(verbosity=2)
