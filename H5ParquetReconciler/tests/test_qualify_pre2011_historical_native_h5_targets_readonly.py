"""Completely fictional H5/private Parquet source concordance qualification tests."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Q=load("historical_native_h5_sample_qualification_test",
       HERE.parent/"tools"/"qualify-pre2011-historical-native-h5-targets-readonly.py")
F=load("historical_native_21year_synthetic_sha_fixture",
       HERE/"test_audit_pre2011_raw_numeric_profile_readonly.py")


def make_record(symbol,year,month,day,factor):
    amount={100000:1,10000:10,0:3}[factor]
    return {"symbol":symbol,"datetime":int(f"{year:04d}{month:02d}{day:02d}0000"),
            "openPrice":1000,"highPrice":1000,"lowPrice":1000,
            "closePrice":1000,"transCount":100,"transAmount":amount}


def synthetic_rows():
    # 1992 SH Q2, Q3, Q4; 1992 SZ Q2; 1993 SH/SZ Q1; 1995 SH Q1.
    return {
        1992:[
            make_record("SH600000",1992,5,2,100000),
            make_record("SH600000",1992,8,3,100000),
            make_record("SH600000",1992,11,4,10000),
            make_record("SZ000001",1992,5,6,10000),
        ],
        1993:[
            make_record("SH600000",1993,2,5,10000),
            make_record("SZ000001",1993,3,7,10000),
        ],
        1995:[
            make_record("SH600000",1995,2,7,0),
        ],
    }


def populate_orig_h5(root,byyear):
    import h5py
    import numpy as np
    folder=root/"HikyuuData"
    folder.mkdir()
    dtype=np.dtype([
        ("datetime","<u8"),("openPrice","<u4"),("highPrice","<u4"),
        ("lowPrice","<u4"),("closePrice","<u4"),
        ("transAmount","<u8"),("transCount","<u8")])
    source=[]
    for rows in byyear.values():
        source.extend(rows)
    for market in ("SH","SZ"):
        path=folder/(market.lower()+"_day.h5")
        with h5py.File(path,"w") as h:
            group=h.create_group("data")
            for symbol in sorted({r["symbol"] for r in source
                                  if r["symbol"].startswith(market)}):
                data=[r for r in source if r["symbol"]==symbol]
                data.sort(key=lambda r:r["datetime"])
                arr=np.zeros(len(data),dtype=dtype)
                for n,row in enumerate(data):
                    for field in dtype.names:
                        arr[n][field]=row[field]
                group.create_dataset(symbol,data=arr)
    return [folder/"sh_day.h5",folder/"sz_day.h5"]


def replace_private_years(private,full,byyear):
    import pyarrow as pa
    import pyarrow.parquet as pq
    report=json.loads(full.read_text(encoding="utf-8"))
    for year,rows in byyear.items():
        base=private/f"native_pre2011_{year}_012345abcdef"
        file=base/"h5-native-day.parquet"
        pq.write_table(pa.Table.from_pylist(rows,schema=Q.SINGLE.schema(pa)),
                       file,compression="zstd")
        manifest=base/"manifest.json"
        m=json.loads(manifest.read_text(encoding="utf-8"))
        m["raw_h5_stockday_rows"]=len(rows)
        m["full_private_parquet_sha256"]=Q.SINGLE.hash_file(file)
        manifest.write_text(json.dumps(m),encoding="utf-8")
        report["yearly"][year-1990]["rows"]=len(rows)
        report["yearly"][year-1990]["parquet_sha256"]=m[
            "full_private_parquet_sha256"]
    report["total_native_rows"]=sum(x["rows"] for x in report["yearly"])
    full.write_text(json.dumps(report),encoding="utf-8")
    return report["total_native_rows"]


@contextmanager
def prepared():
    with tempfile.TemporaryDirectory() as tmp:
        home=Path(tmp)
        reports=home/"reports"
        reports.mkdir()
        private=home/"work"/"unified_parquet"/"pre2011_native_h5_raw"
        private.mkdir(parents=True)
        root=home/"source_market"
        root.mkdir()
        full=reports/"verified-21year-source-safe.json"
        out=reports/"historical-h5-targets-qualified.json"
        work=home/"work"/"h5_mirror"/"historical_native_qualification"
        with (patch.object(Q.P,"REPORTS",reports),
              patch.object(Q.P,"TOTAL_ROWS",25),
              patch.object(Q.SINGLE,"PRIVATE",private),
              patch.object(Q.SINGLE,"MODULE",home),
              patch.object(Q,"MODULE",home),
              patch.object(Q,"WORK",work)):
            F.make_21(private,full)
            rows=synthetic_rows()
            replace_private_years(private,full,rows)
            originals=populate_orig_h5(root,rows)
            yield root,private,full,out,work,originals


class QualifyHistoricalHikyuuNativeTargetTests(unittest.TestCase):
    def test_full21_seven_selected_original_h5_scalar_matches_and_safe(self):
        with prepared() as (root,private,full,out,work,originals):
            old={p:hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in [*originals,*private.rglob("*.parquet")]}
            report=Q.run(root,full,"012345abcdef",out)
            self.assertEqual(report["sample_count"],7)
            self.assertFalse(report["hikyuu_native_driver_called"])
            self.assertTrue(report["private_raw_original_h5_integer_rows_identical"])
            self.assertTrue(report["original_h5_file_stat_unchanged"])
            self.assertFalse(report["original_h5_full_content_sha256_rechecked"])
            self.assertFalse(report["purchased_parquet_opened"])
            self.assertFalse(report["historical_native_units_or_securities_certified"])
            self.assertFalse(report["standardized_parquet_or_h5_mirror_created"])
            self.assertFalse(report["production_or_private_active_pointer_modified"])
            self.assertEqual(old,{p:hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in old})
            manifest=work/"native_targets_012345abcdef"/"selected-original-h5-native-targets.json"
            self.assertTrue(manifest.is_file())
            private_doc=json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(private_doc["sample_selections"]),7)
            self.assertEqual(Q.SINGLE.hash_file(manifest),
                             report["private_selection_manifest_sha256"])
            doc=out.read_text(encoding="utf-8")
            for prohibited in ("SH600000","SZ000001","19920502","19930205",
                               "HikyuuData","source_market",
                               '"transAmount"','"transCount"','"openPrice"'):
                self.assertNotIn(prohibited,doc)

    def test_private_selection_source_index_matches_original_sorted_stock(self):
        with prepared() as (root,_private,full,out,work,_originals):
            Q.run(root,full,"012345abcdef",out)
            p=work/"native_targets_012345abcdef"/"selected-original-h5-native-targets.json"
            d=json.loads(p.read_text(encoding="utf-8"))
            sh1992=[r for r in d["sample_selections"] if
                    r["year"]==1992 and r["market"]=="SH"]
            self.assertEqual([r["source_native_stock_index"] for r in sh1992],
                             [0,1,2])
            self.assertEqual([r["source_stock_total_day_count"] for r in sh1992],
                             [5,5,5])

    def test_original_h5_value_divergence_is_not_silently_accepted(self):
        import h5py
        with prepared() as (root,_private,full,out,work,originals):
            with h5py.File(originals[0],"r+") as h:
                h["data"]["SH600000"][0] = (
                    199205020000,999,1000,1000,1000,1,100)
            with self.assertRaisesRegex(ValueError,"differs"):
                Q.run(root,full,"012345abcdef",out)
            self.assertFalse(out.exists())
            self.assertFalse(work.exists())

    def test_missing_h5_day_or_duplicate_rejected(self):
        import h5py
        with prepared() as (root,_private,full,out,work,originals):
            with h5py.File(originals[0],"r+") as h:
                ds=h["data"]["SH600000"]
                row=list(ds[0])
                row[0]=199205030000
                ds[0]=tuple(row)
            with self.assertRaisesRegex(ValueError,"missing or duplicated"):
                Q.run(root,full,"012345abcdef",out)
            self.assertFalse(out.exists())

    def test_private_raw_corruption_refused_before_original_source_reads(self):
        with prepared() as (root,private,full,out,work,_originals):
            p=private/"native_pre2011_1992_012345abcdef"/"h5-native-day.parquet"
            with p.open("ab") as f:
                f.write(b"corrupt")
            with self.assertRaisesRegex(ValueError,"SHA"):
                Q.run(root,full,"012345abcdef",out)
            self.assertFalse(out.exists())

    def test_missing_required_cohort_refused(self):
        with prepared() as (root,private,full,out,work,_originals):
            # Replace 1992 SH-Q2 F100000 sample with an F10000 row.
            import pyarrow as pa
            import pyarrow.parquet as pq
            folder=private/"native_pre2011_1992_012345abcdef"
            file=folder/"h5-native-day.parquet"
            rows=pq.read_table(file).to_pylist()
            rows[0]["transAmount"]=10
            pq.write_table(pa.Table.from_pylist(rows,schema=Q.SINGLE.schema(pa)),
                           file,compression="zstd")
            mfile=folder/"manifest.json"
            m=json.loads(mfile.read_text(encoding="utf-8"))
            sha=Q.SINGLE.hash_file(file)
            m["full_private_parquet_sha256"]=sha
            mfile.write_text(json.dumps(m),encoding="utf-8")
            safe=json.loads(full.read_text(encoding="utf-8"))
            safe["yearly"][2]["parquet_sha256"]=sha
            full.write_text(json.dumps(safe),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"No positive"):
                Q.run(root,full,"012345abcdef",out)
            self.assertFalse(work.exists())

    def test_reject_existing_safe_and_run_id_and_source_symlinks(self):
        with prepared() as (root,private,full,out,work,originals):
            out.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"new direct-child"):
                Q.run(root,full,"012345abcdef",out)
            self.assertEqual(out.read_text(encoding="utf-8"),"protected")
            out.unlink()
            with self.assertRaisesRegex(ValueError,"run id"):
                Q.run(root,full,"bad/runid",out)
            Q.run(root,full,"012345abcdef",out)
            out.unlink()
            with self.assertRaisesRegex(ValueError,"already exists"):
                Q.run(root,full,"012345abcdef",out)
            self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
