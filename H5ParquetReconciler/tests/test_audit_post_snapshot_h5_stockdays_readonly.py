"""Purely synthetic H5/PQ post-snapshot stock-day audit: no original market."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    tool=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


A=load("h5_post_snapshot_audit_test",
       HERE.parent/"tools"/"audit-post-snapshot-h5-stockdays-readonly.py")
F=load("h5_post_snapshot_audit_fixture",
       HERE/"test_append_private_purchased_day_date_delta.py")

SYMS=("SH600000","SZ000001","SH600519")


def h5_record(day,price=10000):
    return (int(day.replace("-",""))*10000,
            price,price+200,price-200,price+100,150000,1100)


def create_h5(root,record_map):
    import h5py
    import numpy as np
    dtype=np.dtype([("datetime","<u8"),("openPrice","<u4"),
                    ("highPrice","<u4"),("lowPrice","<u4"),
                    ("closePrice","<u4"),("transAmount","<u8"),
                    ("transCount","<u8")])
    folder=root/"HikyuuData"
    folder.mkdir(parents=True,exist_ok=True)
    for market in ("sh","sz"):
        with h5py.File(folder/(market+"_day.h5"),"w") as h5:
            data=h5.create_group("data")
            for sym,rows in record_map.items():
                if sym[:2].lower()==market:
                    data.create_dataset(sym,data=np.array(
                        rows,dtype=dtype),dtype=dtype)


@contextmanager
def ready():
    with F.ready(rows={}) as (
            base,parent_sha,delta,out,purchased,stat,data):
        parent=base.work/"unified_parquet"
        root=base.module/"synthetic_market_readonly"
        create_h5(root,{
            "SH600000":[h5_record("2026-10-14"),h5_record("2026-10-15")],
            "SZ000001":[h5_record("2026-10-14")],
            "SH600519":[h5_record("2026-10-14"),h5_record("2026-10-15"),
                        h5_record("2026-10-16")],
        })
        safe=base.reports/"h5-post-snapshot-availability.json"
        bought={
            "SH600000":[F.stock_bar("SH600000","2026-10-14",10.1)],
            "SZ000001":[F.stock_bar("SZ000001","2026-10-15",20.1)],
            "SH600519":[],
        }
        def fake(root,sym,period,first,last,**kw):
            return F.purchased_result(sym,bought.get(sym,[]),first,last)
        with patch.object(A,"DATE",F.A), \
             patch.object(A,"READER",F.A.READER), \
             patch.object(A,"MODULE",base.module), \
             patch.object(F.A.PURCHASED,"query_bars",side_effect=fake):
            yield base,root,parent_sha,safe,bought,purchased,stat


def audit(root,parent_sha,safe,symbols=SYMS,
          first="2026-10-14",last="2026-10-29"):
    return A.audit(root,parent_sha,list(symbols),first,last,safe)


class PostSnapshotSelectedStockdayAuditTests(unittest.TestCase):
    def test_real_synthetic_h5_and_purchased_dates_classified(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            original={p:A.READER.sha256_file(p) for p in (
                b.pqfile,b.manifest_file,b.safe_file)}
            r=audit(root,sha,safe)
            self.assertEqual(r["observed_h5_stock_days"],6)
            self.assertEqual(r["observed_purchased_stock_days"],2)
            self.assertEqual(r["selected_stockdays_both_sources"],1)
            self.assertEqual(r["selected_stockdays_h5_only_candidate"],5)
            self.assertEqual(r["selected_stockdays_purchased_only"],1)
            self.assertEqual(r["selected_stockdays_neither_source"],41)
            self.assertEqual(r["selected_calendar_days"],16)
            self.assertEqual(r["parent_joined_version_sha256"],sha)
            self.assertFalse(r["whole_market_date_purchased_absence_certified"])
            self.assertFalse(r["whole_market_h5_date_completeness_certified"])
            self.assertFalse(r["selected_stockday_candidates_authorized_for_staging"])
            self.assertFalse(r["h5_volume_amount_physical_units_certified"])
            self.assertFalse(r["production_query_route_modified"])
            self.assertEqual(original,{p:A.READER.sha256_file(p) for p in original})
            self.assertTrue(safe.is_file())
            self.assertEqual(purchased.call_count,3)
            self.assertEqual(stat.call_count,2)
            for forbidden in ("SH600000","SZ000001","SH600519","150000",
                              "synthetic_market_readonly","150000.25"):
                self.assertNotIn(forbidden,safe.read_text(encoding="utf-8"))

    def test_all_missing_purchase_is_still_unqualified_h5_only_candidate(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            bought.clear()
            r=audit(root,sha,safe)
            self.assertEqual(r["observed_h5_stock_days"],6)
            self.assertEqual(r["observed_purchased_stock_days"],0)
            self.assertEqual(r["selected_stockdays_h5_only_candidate"],6)
            self.assertFalse(r["selected_stockday_candidates_authorized_for_staging"])
            self.assertFalse(r["ready_for_full_market_mirror"])

    def test_no_h5_dates_does_not_invent_an_h5_fallback(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            import h5py
            for market in ("sh","sz"):
                path=root/"HikyuuData"/(market+"_day.h5")
                with h5py.File(path,"r+") as f:
                    for symbol in f["data"]:
                        del f["data"][symbol]
            with self.assertRaisesRegex(ValueError,"dataset not found"):
                audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_duplicate_h5_stockday_in_window_fails_closed(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            import h5py,numpy as np
            path=root/"HikyuuData"/"sh_day.h5"
            with h5py.File(path,"r+") as f:
                ds=f["data"]["SH600000"]
                old=ds[:]
                dtype=ds.dtype
                del f["data"]["SH600000"]
                f["data"].create_dataset("SH600000",
                         data=np.array([old[0],old[0],old[1]],dtype=dtype))
            with self.assertRaisesRegex(ValueError,"Unsorted/duplicate"):
                audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_original_h5_geometry_invalid_refused(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            import h5py
            path=root/"HikyuuData"/"sz_day.h5"
            with h5py.File(path,"r+") as f:
                ds=f["data"]["SZ000001"]
                rec=ds[0]
                rec["highPrice"]=1
                ds[0]=rec
            with self.assertRaisesRegex(ValueError,"geometry invalid"):
                audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_original_h5_timestamp_outside_or_invalid_key_refused(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            import h5py
            path=root/"HikyuuData"/"sz_day.h5"
            with h5py.File(path,"r+") as f:
                ds=f["data"]["SZ000001"]
                rec=ds[0]
                rec["datetime"]=202610141200
                ds[0]=rec
            with self.assertRaisesRegex(ValueError,"invalid selected H5 day key"):
                audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_malformed_h5_field_layout_refused(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            import h5py,numpy as np
            path=root/"HikyuuData"/"sz_day.h5"
            with h5py.File(path,"r+") as f:
                del f["data"]["SZ000001"]
                f["data"].create_dataset(
                    "SZ000001",data=np.array([202610140000],dtype="u8"))
            with self.assertRaisesRegex(ValueError,"field contract"):
                audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_original_h5_modified_during_audit_refused(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            original=A.h5_selected_keys
            def changed(*args,**kwargs):
                result=original(*args,**kwargs)
                path=root/"HikyuuData"/"sz_day.h5"
                with path.open("ab") as stream:
                    stream.write(b"changed-after-h5-selection")
                return result
            with patch.object(A,"h5_selected_keys",side_effect=changed):
                with self.assertRaisesRegex(ValueError,"source or logical parent changed"):
                    audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_purchased_source_stat_change_refused(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            before={"manifest_sha256_stat_only":"a"*64,"manifest_file_count":2}
            after={"manifest_sha256_stat_only":"b"*64,"manifest_file_count":2}
            stat.side_effect=[before,after]
            with self.assertRaisesRegex(ValueError,"inventory changed"):
                audit(root,sha,safe)
            self.assertFalse(safe.exists())

    def test_parent_version_tampered_blocks_both_original_sources(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            p=F.A.REG.VERSIONS/(sha+".json")
            with p.open("a",encoding="utf-8") as stream:
                stream.write("tampered")
            with self.assertRaises(ValueError):
                audit(root,sha,safe)
            purchased.assert_not_called()
            self.assertFalse(safe.exists())

    def test_invalid_stock_and_date_window_refused_before_original_scan(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            for symbols,first,last in (
                (["BJ899999"],"2026-10-14","2026-10-29"),
                (["sh600000"],"2026-10-14","2026-10-29"),
                (["SH600000"]*2,"2026-10-14","2026-10-29"),
                (SYMS,"2026-10-08","2026-10-29"),
                (SYMS,"2026-10-14","2026-12-31")
            ):
                with self.subTest(symbols=symbols,first=first,last=last):
                    with self.assertRaises(ValueError):
                        audit(root,sha,safe,symbols,first,last)
            purchased.assert_not_called()

    def test_existing_safe_report_is_not_overwritten(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            safe.write_text("protected",encoding="utf-8")
            with self.assertRaises(ValueError):
                audit(root,sha,safe)
            self.assertEqual(safe.read_text(),"protected")

    def test_reports_outside_module_denied(self):
        with ready() as (b,root,sha,safe,bought,purchased,stat):
            with self.assertRaises(ValueError):
                audit(root,sha,b.module/"unsafe.json")
            self.assertFalse(safe.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
