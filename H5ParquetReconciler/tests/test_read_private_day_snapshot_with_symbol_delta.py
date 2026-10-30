"""Synthetic parent + Parquet stock delta joined-read tests (never real market)."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


J=load("private_joined_day_delta_test",
       HERE.parent/"tools"/"read-private-day-snapshot-with-symbol-delta.py")
F=load("private_joined_day_fixture",
       HERE/"test_append_private_unified_day_symbol_delta.py")


@contextmanager
def ready():
    with F.fixture() as (base,parent,folder,delta_safe,batch):
        result=F.append(base,parent,folder,delta_safe)
        self_safe=base.reports/"joined-safe.json"
        # The imported join tool uses its own module instance, but every
        # operation must reference the SAME temporary, synthetic fixture.
        with patch.object(J,"MODULE",base.module), \
             patch.object(J,"READER",F.A.READER), \
             patch.object(J,"VERSION",F.A.VERSION), \
             patch.object(J.ADD,"MODULE",F.A.MODULE), \
             patch.object(J.ADD,"WORK",F.A.WORK), \
             patch.object(J.ADD,"DELTAS",F.A.DELTAS), \
             patch.object(J.ADD,"VERSION",F.A.VERSION), \
             patch.object(J.ADD,"READER",F.A.READER):
            yield base,parent,folder,delta_safe,self_safe,batch,result


def join(parent,delta_safe,out,symbols=("SH600000","SZ000001","SH600519"),
         first="2026-09-30",last="2026-10-08"):
    return J.read_joined(parent,delta_safe,list(symbols),first,last,out)


def resign_delta(folder,delta_safe,metadata=None,source=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    mfile=folder/"manifest.json"
    pqfile=folder/"day.parquet"
    meta=json.loads(mfile.read_text(encoding="utf-8"))
    safe=json.loads(delta_safe.read_text(encoding="utf-8"))
    if source is not None:
        pq.write_table(pa.Table.from_pylist(
            source,schema=J.READER.expected_schema(pa)),pqfile)
        meta["delta_parquet_sha256"]=J.READER.sha256_file(pqfile)
        safe["delta_parquet_sha256"]=meta["delta_parquet_sha256"]
    if metadata is not None:
        metadata(meta)
    mfile.write_text(json.dumps(meta),encoding="utf-8")
    safe["delta_manifest_sha256"]=J.READER.sha256_file(mfile)
    delta_safe.write_text(json.dumps(safe),encoding="utf-8")


class JoinedPrivateSnapshotAndDeltaTests(unittest.TestCase):
    def test_fictional_real_arrow_parent_plus_delta_full_view(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            old={p:J.READER.sha256_file(p) for p in (
                b.pqfile,b.manifest_file,b.safe_file)}
            delta={p:J.READER.sha256_file(p) for p in (
                folder/"day.parquet",folder/"manifest.json",safe)}
            result=join(parent,safe,out)
            summary=result["safe_summary"]
            self.assertEqual(summary["joined_full_rows"],5)
            self.assertEqual(summary["joined_stocks"],3)
            self.assertEqual(summary["parent_rows"],3)
            self.assertEqual(summary["delta_rows"],2)
            self.assertEqual(summary["selected_rows"],5)
            self.assertEqual(summary["selected_purchased_rows"],2)
            self.assertEqual(summary["selected_h5_gap_candidate_rows"],3)
            self.assertTrue(summary["parent_delta_full_schema_keys_counts_and_hashes_verified"])
            self.assertFalse(summary["private_snapshot_pointer_read_or_modified"])
            self.assertTrue(summary["no_live_market_source_freshness_recheck"])
            self.assertEqual(len(result["bars_by_symbol"]["SH600519"]),2)
            self.assertEqual(old,{p:J.READER.sha256_file(p) for p in old})
            self.assertEqual(delta,{p:J.READER.sha256_file(p) for p in delta})
            batch.assert_called_once()
            self.assertFalse((b.work/"unified_parquet"/"active-private-snapshot.json").exists())
            for private in ("150000.25","SH600519","SH600000","SZ000001",
                            "HikyuuData","test-market-synthetic"):
                self.assertNotIn(private,out.read_text())

    def test_single_delta_stock_subset_and_date_window(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            result=join(parent,safe,out,("SH600519",),"2026-10-08","2026-10-08")
            s=result["safe_summary"]
            self.assertEqual(s["selected_rows"],1)
            self.assertEqual(s["selected_purchased_rows"],0)
            self.assertEqual(s["selected_h5_gap_candidate_rows"],1)
            self.assertEqual(s["joined_full_rows"],5)

    def test_tampered_delta_parquet_refused_without_output(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            with (folder/"day.parquet").open("ab") as f:
                f.write(b"tampered")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                join(parent,safe,out)
            self.assertFalse(out.exists())

    def test_tampered_delta_manifest_refused_without_output(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            with (folder/"manifest.json").open("ab") as f:
                f.write(b"tampered")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                join(parent,safe,out)
            self.assertFalse(out.exists())

    def test_tampered_parent_refused_before_delta_decode(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            with b.pqfile.open("ab") as f:
                f.write(b"changed")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                join(parent,safe,out)
            self.assertFalse(out.exists())

    def test_changed_parent_version_cannot_rebind_delta(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            false_parent="b"*64
            with self.assertRaises(ValueError):
                join(false_parent,safe,out)
            self.assertFalse(out.exists())

    def test_delta_forged_manifests_must_match_real_parent(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            resign_delta(folder,safe,
                metadata=lambda m:m.update(
                    parent_parquet_sha256="f"*64))
            with self.assertRaisesRegex(ValueError,"provenance"):
                join(parent,safe,out)
            self.assertFalse(out.exists())

    def test_rebranded_parent_symbol_rejected_even_if_hashes_resigned(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            def wrong(m):
                m["new_symbols"]=["SH600000"]
                m["per_symbol_counts"]={"SH600000":
                    m["per_symbol_counts"]["SH600519"]}
            resign_delta(folder,safe,metadata=wrong)
            with self.assertRaisesRegex(ValueError,"overlaps parent"):
                join(parent,safe,out)
            self.assertFalse(out.exists())

    def test_duplicated_stockday_in_delta_rejected_after_resign(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            import pyarrow.parquet as pq
            rows=pq.read_table(folder/"day.parquet").to_pylist()
            rows[1]["trading_date"]=rows[0]["trading_date"]
            resign_delta(folder,safe,source=rows)
            with self.assertRaisesRegex(ValueError,"Duplicate"):
                join(parent,safe,out)

    def test_wrong_delta_timestamp_rejected_after_resign(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            import pyarrow.parquet as pq
            rows=pq.read_table(folder/"day.parquet").to_pylist()
            rows[1]["ts"]=rows[0]["ts"]
            resign_delta(folder,safe,source=rows)
            with self.assertRaisesRegex(ValueError,"timestamp"):
                join(parent,safe,out)

    def test_existing_output_never_overwritten(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            out.write_text("existing",encoding="utf-8")
            with self.assertRaises(ValueError):
                join(parent,safe,out)
            self.assertEqual(out.read_text(),"existing")

    def test_output_outside_reports_rejected(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            with self.assertRaises(ValueError):
                join(parent,safe,b.module/"joined.json")
            self.assertFalse(out.exists())

    def test_new_stock_not_in_joined_view_rejected(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            with self.assertRaisesRegex(ValueError,"outside parent"):
                join(parent,safe,out,("BJ899999",))
            self.assertFalse(out.exists())

    def test_invalid_delta_safe_flags_refused(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            data=json.loads(safe.read_text())
            data["ready_for_full_market_mirror"]=True
            safe.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,"not a verified"):
                join(parent,safe,out)
            self.assertFalse(out.exists())

    def test_delta_source_changed_after_decode_fails_closed(self):
        with ready() as (b,parent,folder,safe,out,batch,created):
            original=J.READER.inspect_rows
            calls=[0]
            def alter_after(rows,manifest):
                info=original(rows,manifest)
                calls[0]+=1
                if calls[0]==2:
                    with (folder/"day.parquet").open("ab") as stream:
                        stream.write(b"changed-after-read")
                return info
            with patch.object(J.READER,"inspect_rows",side_effect=alter_after):
                with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                    join(parent,safe,out)
            self.assertEqual(calls[0],2)
            self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
