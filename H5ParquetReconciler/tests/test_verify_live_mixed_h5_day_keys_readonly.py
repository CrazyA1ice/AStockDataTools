"""Synthetic original H5/PQ only: exact 83-key live verification regression tests."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch


HERE=Path(__file__).resolve().parent


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


M=load("live_mixed_key_verifier_under_test",
       HERE.parent/"tools"/"verify-live-mixed-h5-day-keys-readonly.py")
OFFTEST=load("mixed_offline_fixture_for_live",
             HERE/"test_plan_private_mixed_h5_day_gaps_offline.py")


def day(date_text,missing=1,matched=1,purchased=1):
    return {
        "date":date_text,
        "h5_only_stockday_candidate_rows":missing,
        "overlapping_source_stockday_rows":matched,
        "purchased_source_stockday_rows":purchased,
        "same_day_overlapping_price_disagreements":0,
        "status":"candidate_requires_exact_stockday_live_recheck",
    }


def files(root,year,dates):
    import h5py
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    base=root/"HikyuuData"
    base.mkdir(parents=True,exist_ok=True)
    source=root/"AllCycleAStockData"/"day"
    source.mkdir(parents=True,exist_ok=True)
    dtype=np.dtype([(field,"i8") for field in M.CORE.H5_FIELDS])
    labels=[int(d.replace("-",""))*10000 for d in dates]
    def records():
        buf=np.zeros(len(labels),dtype=dtype)
        buf["datetime"]=labels
        for field in M.CORE.H5_FIELDS:
            if field!="datetime":
                buf[field]=10000
        return buf
    for market in ("sh","sz","bj"):
        with h5py.File(base/f"{market}_day.h5","w") as fh:
            group=fh.create_group("data")
            if market=="sh":
                group.create_dataset("SH600000",data=records())
            if market=="sz":
                group.create_dataset("SZ000001",data=records())
    ts=[int(datetime(d.year,d.month,d.day,
                     tzinfo=M.CORE.UTC8).timestamp()*1000)
        for d in (date.fromisoformat(x) for x in dates)]
    table=pa.table({"ts":pa.array(ts,type=pa.int64()),
                    "symbol":pa.array(["600000.XSHG"]*len(ts))})
    pq.write_table(table,source/f"{year}-04.parquet",row_group_size=1)
    return source/f"{year}-04.parquet"


class PureMixedKeyGateTests(unittest.TestCase):
    def test_classify_real_exact_one_missing_per_day(self):
        rows=[day("2026-04-08"),day("2026-04-09")]
        first=202604080000
        second=202604090000
        h={("SH600000",first),("SZ000001",first),
           ("SH600000",second),("SZ000001",second)}
        p={("SH600000",first),("SH600000",second)}
        output,missing=M.classify_exact_days(2026,rows,h,p)
        self.assertEqual([r["h5_only_verified_unique_stockdays"]
                          for r in output],[1,1])
        self.assertEqual(set(missing),h-p)
        self.assertNotIn(("SH600000",first),missing)

    def test_missing_key_quantity_mismatch_fails_closed(self):
        row=day("2026-04-08",missing=2)
        with self.assertRaisesRegex(ValueError,"Live exact"):
            M.classify_exact_days(2026,[row],
                {("SH600000",202604080000),("SZ000001",202604080000)},
                {("SH600000",202604080000)})

    def test_new_purchased_stockday_prevents_stale_missing_claim(self):
        row=day("2026-04-08")
        h={("SH600000",202604080000),("SZ000001",202604080000)}
        with self.assertRaisesRegex(ValueError,"Live exact"):
            M.classify_exact_days(2026,[row],h,h)

    def test_wrong_matched_count_fails_closed(self):
        row=day("2026-04-08",matched=2)
        with self.assertRaisesRegex(ValueError,"Live exact"):
            M.classify_exact_days(2026,[row],
                {("SH600000",202604080000),("SZ000001",202604080000)},
                {("SH600000",202604080000)})

    def test_selected_day_set_cannot_escape_audit(self):
        row=day("2026-04-08")
        h={("SH600000",202604080000),("SZ000001",202604080000),
           ("SZ000001",202604090000)}
        p={("SH600000",202604080000)}
        with self.assertRaisesRegex(ValueError,"escaped"):
            M.classify_exact_days(2026,[row],h,p)

    def test_synthetic_h5_and_parquet_read_only_key_join(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"source"
            original=files(root,2026,("2026-04-08","2026-04-09"))
            old=original.read_bytes()
            h=M.scan_h5_keys(root,2026,
                             [day("2026-04-08"),day("2026-04-09")])
            p,n=M.scan_parquet_keys(root,2026,
                                    [day("2026-04-08"),day("2026-04-09")])
            out,missing=M.classify_exact_days(2026,
                               [day("2026-04-08"),day("2026-04-09")],h,p)
            self.assertEqual(len(missing),2)
            self.assertTrue(all(s=="SZ000001" for s,t in missing))
            self.assertEqual(sum(x["h5_only_verified_unique_stockdays"]
                                 for x in out),2)
            self.assertEqual(original.read_bytes(),old)
            self.assertGreaterEqual(n,2)

    def test_duplicate_purchased_parquet_key_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"sources"
            target=files(root,2026,("2026-04-08",))
            t=pq.read_table(target)
            pq.write_table(pa.concat_tables([t,t]),target)
            with self.assertRaisesRegex(ValueError,"Duplicated purchased"):
                M.scan_parquet_keys(root,2026,[day("2026-04-08")])

    def test_no_purchased_parquet_files_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"original"
            (root/"AllCycleAStockData"/"day").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,"No purchased"):
                M.scan_parquet_keys(root,2016,[day("2016-08-25")])

    def test_source_stat_digest_detects_changed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"market"
            target=files(root,2026,("2026-04-08",))
            first=M.state_digest(root,(2026,))
            with target.open("ab") as stream:
                stream.write(b"changed")
            second=M.state_digest(root,(2026,))
            self.assertNotEqual(first,second)

    def test_manifest_directory_must_be_new_and_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            private=root/"work"/"unified_parquet"/"mixed_day_key_manifests"
            private.mkdir(parents=True)
            with patch.object(M,"WORK",root/"work"),patch.object(M,"PRIVATE",private):
                accepted=M.private_folder(private/"keys_0123456789ab")
                self.assertEqual(accepted.parent,private)
                for invalid in (private/"bad",root/"outside"/"keys_0123456789ab"):
                    with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                        M.private_folder(invalid)
                accepted.mkdir()
                with self.assertRaises(ValueError):
                    M.private_folder(accepted)

    def test_actual_offline_gate_recomputes_original_plan_from_sha(self):
        ledger,reports=OFFTEST.example()
        output=OFFTEST.M.analyze(ledger,reports)
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/"reports"
            report.mkdir()
            paths={}
            for name,blob in [("ledger.json",ledger),*reports.items(),
                              ("plan.json",json.dumps(output).encode())]:
                path=report/name
                path.write_bytes(blob)
                paths[name]=path
            with patch.object(M,"REPORTS",report),patch.object(M.OFFLINE,"REPORTS",report):
                originals,dates=M.verified_existing_plan(
                    paths["ledger.json"],paths["day-2016-safe.json"],
                    paths["day-2026-safe.json"],paths["plan.json"])
                self.assertEqual(len(originals),4)
                self.assertEqual(sum(x["h5_only_stockday_candidate_rows"]
                                     for y in dates.values() for x in y),83)
                self.assertNotIn("2026-07-16",
                                 [x["date"] for y in dates.values() for x in y])

    def test_source_report_tamper_breaks_sha_link_even_if_plan_unchanged(self):
        ledger,reports=OFFTEST.example()
        output=OFFTEST.M.analyze(ledger,reports)
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/"reports"
            report.mkdir()
            paths={}
            for name,blob in [
                    ("ledger.json",ledger),
                    *reports.items(),
                    ("plan.json",json.dumps(output).encode())]:
                path=report/name
                path.write_bytes(blob)
                paths[name]=path
            paths["day-2016-safe.json"].write_bytes(
                reports["day-2016-safe.json"]+b" ")
            with patch.object(M,"REPORTS",report):
                with self.assertRaisesRegex(ValueError,"SHA"):
                    M.verified_existing_plan(
                        paths["ledger.json"],paths["day-2016-safe.json"],
                        paths["day-2026-safe.json"],paths["plan.json"])


if __name__=="__main__":
    unittest.main(verbosity=2)
