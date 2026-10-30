"""Synthetic purchased-only new trading-date Parquet materialization tests."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A=load("private_new_date_purchase_delta_test",
       HERE.parent/"tools"/"append-private-purchased-day-date-delta.py")
F=load("private_new_date_purchase_delta_fixture",
       HERE/"test_register_private_joined_day_logical_version.py")


def stock_bar(sym,day,price):
    ts=int(datetime.fromisoformat(day).replace(
        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    return {"symbol":sym,"period":"day","trading_date":day,
            "source_timestamp_ms":ts,
            "open":float(price),"high":float(price+.2),
            "low":float(price-.2),"close":float(price+.1),
            "volume":1100.0,"amount":150000.25}


def purchased_result(sym,rows,first="2026-10-09",last="2026-10-12"):
    return {"bars":rows,"safe_summary":{
        "format":"AStockDataTools purchased Parquet bounded query summary v1",
        "symbol":sym,"period":"day",
        "from_date":first,"to_date":last,
        "matching_bar_count":len(rows),
        "no_h5_read":True,"source_market_files_modified":False,
        "no_automatic_gaps_fill":True,
        "source_quantity_unit_rescaling_applied":False,
        "no_raw_ohlcva_in_safe_summary":True,"local_cache_used":False,
        "query_delivery":"parquet_source_scan",
    }}


@contextmanager
def ready(rows=None):
    with F.ready() as (base,parent,folder,delta,versions,active,lock,batch):
        old=F.R.prepare(parent,delta)
        sha=old["version_sha256"]
        work=base.work/"unified_parquet"
        delta_parent=work/"date_deltas"
        delta_dir=delta_parent/"date_delta_012345abcdef"
        out=base.reports/"purchased-new-date-safe.json"
        symbols=("SH600000","SZ000001","SH600519")
        data=rows if rows is not None else {
          "SH600000":[stock_bar("SH600000","2026-10-09",10.1)],
          "SZ000001":[stock_bar("SZ000001","2026-10-12",20.1)],
          "SH600519":[stock_bar("SH600519","2026-10-09",30.1)],
        }
        def lookup(root,sym,period,first,last,**kw):
            return purchased_result(sym,data.get(sym,[]),first,last)
        signature={
            "manifest_sha256_stat_only":"a"*64,"manifest_file_count":2,
        }
        with patch.object(A,"REG",F.R), \
             patch.object(A,"READER",F.R.READER), \
             patch.object(A,"MODULE",base.module), \
             patch.object(A,"WORK",work), \
             patch.object(A,"PARTITIONS",delta_parent), \
             patch.object(A,"REPORTS",base.reports), \
             patch.object(A.PURCHASED,"query_bars",side_effect=lookup) as purchased, \
             patch.object(A.PURCHASED.private_cache,"source_signature",
                          return_value=signature) as inventory:
            yield base,sha,delta_dir,out,purchased,inventory,data


def run(base,sha,delta_dir,out,
        symbols=("SH600000","SZ000001","SH600519"),
        first="2026-10-09",last="2026-10-12"):
    return A.append(base.module/"fictional-only-purchased-source",
                    sha,list(symbols),first,last,delta_dir,out)


class PurchasedOnlyNewDateDeltaTests(unittest.TestCase):
    def test_fictional_new_date_partition_uses_only_purchased_real_arrow(self):
        import pyarrow.parquet as pq
        with ready() as (b,sha,folder,out,query,inventory,data):
            watched=(b.pqfile,b.manifest_file,b.safe_file)
            before={p:A.READER.sha256_file(p) for p in watched}
            result=run(b,sha,folder,out)
            self.assertEqual(result["new_purchased_rows"],3)
            self.assertEqual(result["stocks_with_new_purchased_rows"],3)
            self.assertTrue(result["new_date_parquet_created"])
            self.assertTrue(result["no_h5_fallback_or_implicit_gap_fill"])
            self.assertFalse(result["private_active_pointers_read_or_modified"])
            self.assertTrue(result["source_stat_proof_is_not_cryptographic_file_hash"])
            self.assertEqual(len(pq.read_table(folder/"day.parquet").to_pylist()),3)
            meta=json.loads((folder/"manifest.json").read_text())
            self.assertEqual(meta["parent_joined_version_sha256"],sha)
            self.assertEqual(meta["per_stock_purchased_counts"],
                             {"SH600000":1,"SZ000001":1,"SH600519":1})
            self.assertEqual(result["delta_parquet_sha256"],
                             A.READER.sha256_file(folder/"day.parquet"))
            self.assertEqual(result["delta_manifest_sha256"],
                             A.READER.sha256_file(folder/"manifest.json"))
            self.assertEqual(before,{p:A.READER.sha256_file(p) for p in watched})
            self.assertFalse((b.work/"unified_parquet"/"active-private-joined-day.json").exists())
            self.assertEqual(query.call_count,3)
            self.assertEqual(inventory.call_count,3)
            for secret in ("SH600000","SZ000001","SH600519","150000.25",
                           "HikyuuData","fictional-only-purchased-source"):
                self.assertNotIn(secret,out.read_text())

    def test_no_purchased_rows_reports_absence_without_empty_delta(self):
        with ready(rows={}) as (b,sha,folder,out,query,inventory,data):
            result=run(b,sha,folder,out)
            self.assertEqual(result["new_purchased_rows"],0)
            self.assertEqual(result["status"],
                             "purchased_new_date_not_available_no_partition")
            self.assertFalse(result["new_date_parquet_created"])
            self.assertIsNone(result["new_date_delta_relative_path"])
            self.assertTrue(out.is_file())
            self.assertFalse(folder.exists())

    def test_earlier_or_overlapping_day_window_rejected_before_purchased(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            for first,last in (("2026-10-08","2026-10-09"),
                               ("2026-09-30","2026-10-08"),
                               ("2026-10-12","2026-10-09"),
                               ("2026-10-9","2026-10-12"),
                               ("2026-10-09","2026-11-15")):
                with self.subTest(first=first,last=last):
                    with self.assertRaisesRegex(ValueError,"later bounded"):
                        run(b,sha,folder,out,first=first,last=last)
            query.assert_not_called()
            self.assertFalse(folder.exists())

    def test_only_registered_stocks_may_gain_new_dates(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            for symbols in (["BJ899999"],["SH600000","BJ899999"]):
                with self.subTest(symbols=symbols):
                    with self.assertRaisesRegex(ValueError,"registered logical parent"):
                        run(b,sha,folder,out,symbols=symbols)
            query.assert_not_called()

    def test_no_duplicate_or_malformed_stock_selectors(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            for symbols in ([],["sh600000"],["SH600000","SH600000"],
                            ["BAD"],["SH600000"]*11):
                with self.subTest(symbols=symbols):
                    with self.assertRaises(ValueError):
                        run(b,sha,folder,out,symbols=symbols)
            query.assert_not_called()

    def test_bad_purchased_source_claim_does_not_write(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            def fake(*args,**kwargs):
                r=purchased_result(args[1],data.get(args[1],[]),
                                   args[3],args[4])
                r["safe_summary"]["no_h5_read"]=False
                return r
            query.side_effect=fake
            with self.assertRaisesRegex(ValueError,"purchased-only cold"):
                run(b,sha,folder,out)
            self.assertFalse(folder.exists())
            self.assertFalse(out.exists())

    def test_zero_price_nan_amount_and_wrong_source_day_refused(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            for field,value,pattern in (
                    ("amount",float("nan"),"nonfinite"),
                    ("open",0.0,"geometry"),
                    ("trading_date","2026-10-10","day/time")):
                with self.subTest(field=field):
                    obj=data["SH600000"][0]
                    old=obj[field]
                    obj[field]=value
                    try:
                        with self.assertRaisesRegex(ValueError,pattern):
                            run(b,sha,folder,out)
                    finally:
                        obj[field]=old
            self.assertFalse(folder.exists())

    def test_purchased_stockday_duplicate_refused(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            data["SH600000"].append(dict(data["SH600000"][0]))
            with self.assertRaisesRegex(ValueError,"Duplicate purchased"):
                run(b,sha,folder,out)
            self.assertFalse(folder.exists())

    def test_bad_timestamp_in_purchased_result_refused(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            data["SH600000"][0]["source_timestamp_ms"]+=60000*60*24
            with self.assertRaisesRegex(ValueError,"day/time"):
                run(b,sha,folder,out)
            self.assertFalse(out.exists())

    def test_stat_source_changed_between_stock_queries_refused(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            before={"manifest_sha256_stat_only":"a"*64,"manifest_file_count":2}
            after={"manifest_sha256_stat_only":"b"*64,"manifest_file_count":2}
            inventory.side_effect=[before,after]
            with self.assertRaisesRegex(ValueError,"inventory changed"):
                run(b,sha,folder,out)
            self.assertFalse(folder.exists())
            self.assertFalse(out.exists())

    def test_stat_source_changed_after_materialization_refused_without_safe(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            before={"manifest_sha256_stat_only":"a"*64,"manifest_file_count":2}
            after={"manifest_sha256_stat_only":"b"*64,"manifest_file_count":2}
            inventory.side_effect=[before,before,after]
            with self.assertRaisesRegex(ValueError,"changed before SAFE"):
                run(b,sha,folder,out)
            self.assertTrue(folder.is_dir())
            self.assertFalse(out.exists())

    def test_registered_parent_tampering_rejected_before_purchased_scan(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            p=b.pqfile
            with p.open("ab") as stream:
                stream.write(b"tampered original base")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                run(b,sha,folder,out)
            query.assert_not_called()

    def test_existing_delta_or_safe_not_overwritten(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            folder.parent.mkdir(parents=True,exist_ok=True)
            folder.mkdir()
            with self.assertRaisesRegex(ValueError,"unused"):
                run(b,sha,folder,out)
            folder.rmdir()
            out.write_text("protected",encoding="utf-8")
            with self.assertRaises(ValueError):
                run(b,sha,folder,out)
            self.assertEqual(out.read_text(),"protected")
            query.assert_not_called()

    def test_external_or_wrong_named_delta_paths_rejected(self):
        with ready() as (b,sha,folder,out,query,inventory,data):
            for p in (b.module/"date_delta_012345abcdef",
                      b.work/"wrong"/"date_delta_012345abcdef",
                      folder/"nested",folder.parent/"delta_bad"):
                with self.subTest(path=p):
                    with self.assertRaises(ValueError):
                        A.outputs(p,out)
            query.assert_not_called()


if __name__=="__main__":
    unittest.main(verbosity=2)
