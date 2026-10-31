"""Synthetic full 22,274 H5-gap candidates; never reads original market data."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,TOOLS/file)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M=load("all_22274_candidate_partitions_test",
       "materialize-private-full-22274-gap-candidates.py")
V=load("all_22274_independent_offline_reader_test",
       "verify-private-full-22274-gap-candidates.py")
WHOLE_DAYS=("2026-10-08","2026-10-09","2026-10-12","2026-10-13")
WHOLE_COUNTS=(5546,5547,5549,5549)
SYMS=tuple(f"SH{prefix}{i:03d}" for prefix in
           ("600","601","603","605","688","689") for i in range(1000))


def stamp(day):
    return int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)


def old_stage(sym,day,source):
    return {"ts":stamp(day),"symbol":sym,"source":source,
            "open":10.0,"high":12.0,"low":9.0,"close":11.0,
            "volume":100.0,"amount":1000.0}


class FullCandidatePartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        import pyarrow.parquet as pq
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.reports=cls.root/"reports"
        cls.reports.mkdir()
        cls.stages=[]
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(f,pa.float64()) for f in M.FIELDS),
            pa.field("source",pa.string()),
        ])
        cls.assert_stage_schema=(tuple(schema.names),tuple(M.PRE.MIXED.STAGE.SCHEMA_FIELDS))
        for day,count in zip(WHOLE_DAYS,WHOLE_COUNTS):
            p=cls.root/"staging"/day
            p.mkdir(parents=True)
            file=p/"day.parquet"
            rows=[old_stage(s,day,"hikyuu_h5_tail_candidate")
                  for s in SYMS[:count]]
            pq.write_table(pa.Table.from_pylist(rows,schema=schema),file)
            cls.stages.append({
                "day":day,"rows":count,
                "stage_dir":p.relative_to(cls.root).as_posix(),
                "parquet_sha256":M.sha(file),
            })
        cls.mixed_rows=[old_stage("SZ000001","2016-08-17",
                                   "hikyuu_h5_mixed_day_candidate")]
        cls.mixed_rows.extend(old_stage(f"SZ000{i:03d}","2026-08-17",
                                        "hikyuu_h5_mixed_day_candidate")
                              for i in range(82))
        cls.expected={(r["symbol"],int(datetime.fromtimestamp(
            r["ts"]/1000,tz=M.CORE.UTC8).strftime("%Y%m%d%H%M")))
                      for r in cls.mixed_rows}
        cls.source_file=cls.root/"mixed-stage.parquet"
        pq.write_table(pa.Table.from_pylist(cls.mixed_rows,schema=schema),cls.source_file)
        cls.mixed_manifest=cls.root/"mixed-stage.json"
        cls.mixed_manifest.write_bytes(b'{"immutable":true}\n')
        cls.mixed_safe=cls.root/"mixed-safe.json"
        cls.mixed_safe.write_bytes(b'{"unverified":true}\n')
        cls.original=cls.reports/"original.json"
        cls.proof={
            "format":M.PRE.FORMAT,
            "candidate_total_new_stockday_rows":22274,
            "whole_day_candidate_rows":22191,
            "mixed_stockday_candidate_rows":83,
            "original_source_stat_sha256":"d"*64,
        }
        cls.original.write_bytes((json.dumps(cls.proof,sort_keys=True)+"\n").encode())
        cls.version={
            "version_sha256":"e"*64,
            "whole_day_overlay_version_sha256":"f"*64,
            "mixed_stage_safe_basename":"mixed-safe.json",
            "whole_day_candidate_rows":22191,
            "mixed_stockday_candidate_rows":83,
            "candidate_total_new_stockday_rows":22274,
            "ready_for_production_query":False,
            "original_preflight_safe_basename":"original.json",
            "original_source_stat_sha256":"d"*64,
            "fresh_recheck_safe_sha256":M.sha(cls.original),
            "mixed_stage_parquet_sha256":M.sha(cls.source_file),
            "mixed_stage_manifest_sha256":M.sha(cls.mixed_manifest),
            "mixed_stage_safe_sha256":M.sha(cls.mixed_safe),
            "original_preflight_safe_sha256":M.sha(cls.original),
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_stage_arrow_schema_names_match_expected(self):
        self.assertEqual(*self.assert_stage_schema)

    def test_exact_full_22191_plus_83_rows_without_duplicated_keys(self):
        with patch.object(M.WHOLE.versioner,"MODULE",self.root),\
             patch.object(M.WHOLE.versioner,"safe_stage_path",side_effect=lambda x:x):
            rows,count=M.collect(self.stages,self.mixed_rows,self.expected)
        self.assertEqual(count,{"whole":22191,"mixed":83})
        self.assertEqual(len(rows[2016]),1)
        self.assertEqual(len(rows[2026]),22273)
        self.assertEqual(rows[2016][0]["value_source"],
                         "private_h5_mixed_stockday_candidate")
        self.assertEqual(sum(x["value_source"]=="private_h5_whole_date_candidate"
                             for x in rows[2026]),22191)

    def test_missing_one_original_mixed_key_rejected(self):
        with patch.object(M.WHOLE.versioner,"MODULE",self.root),\
             patch.object(M.WHOLE.versioner,"safe_stage_path",side_effect=lambda x:x):
            with self.assertRaisesRegex(ValueError,"incomplete"):
                M.collect(self.stages,self.mixed_rows[:82],self.expected)

    def test_duplicate_mixed_source_key_rejected(self):
        rows=list(self.mixed_rows)
        rows[-1]=rows[-2]
        with patch.object(M.WHOLE.versioner,"MODULE",self.root),\
             patch.object(M.WHOLE.versioner,"safe_stage_path",side_effect=lambda x:x):
            with self.assertRaisesRegex(ValueError,"differs"):
                M.collect(self.stages,rows,self.expected)

    def test_quarantined_july_16_always_rejected(self):
        with self.assertRaisesRegex(ValueError,"quarantined"):
            M.normalise(old_stage("SH600000","2026-07-16",
                        "hikyuu_h5_mixed_day_candidate"),
                        "hikyuu_h5_mixed_day_candidate")

    def test_h5_candidate_wrong_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"distinction"):
            M.normalise(old_stage("SH600000","2026-10-08",
                         "hikyuu_h5_mixed_day_candidate"),
                         "hikyuu_h5_tail_candidate","2026-10-08")

    def test_invalid_price_geometry_rejected(self):
        r=old_stage("SH600000","2026-10-08","hikyuu_h5_tail_candidate")
        r["high"]=9.0
        with self.assertRaisesRegex(ValueError,"geometry"):
            M.normalise(r,"hikyuu_h5_tail_candidate","2026-10-08")

    def test_nonfloat64_volume_rejected(self):
        r=old_stage("SH600000","2026-10-08","hikyuu_h5_tail_candidate")
        r["volume"]=100
        with self.assertRaisesRegex(ValueError,"Nonfloat64"):
            M.normalise(r,"hikyuu_h5_tail_candidate","2026-10-08")

    def test_unsafe_snapshot_destination_blocked_before_gate(self):
        with patch.object(M,"CANDIDATES",self.root/"candidate_snapshots"),\
             patch.object(M,"REPORTS",self.reports):
            with self.assertRaisesRegex(ValueError,"NEW direct"):
                M.guarded_paths(self.root/"outside","unused.json","unused2.json")

    def test_all_partitions_full_roundtrip_and_independent_reader(self):
        import pyarrow
        folder=self.root/"work"/"unified_parquet"/"candidate_snapshots"/"candidates_abcdefabcdef"
        safe=self.reports/"materialized.json"
        fresh=self.reports/"fresh.json"
        final=self.reports/"verified.json"
        def fake_verify(*args,**kwargs):
            fresh.write_bytes(self.original.read_bytes())
            return dict(self.proof)
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"WORK",self.root/"work"/"unified_parquet"),\
             patch.object(M,"CANDIDATES",folder.parent),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M.PRE,"REPORTS",self.reports),\
             patch.object(M.PRE,"new_report",side_effect=lambda p:Path(p)),\
             patch.object(M.PRE,"verify",side_effect=fake_verify) as gate,\
             patch.object(M.REG,"LOCK",self.root/"no-registration-lock"),\
             patch.object(M.REG,"load_version",return_value=self.version),\
             patch.object(M.REG,"read_audit",return_value=(self.original,self.original.read_bytes(),self.proof)),\
             patch.object(M.PRE.KEYS,"state_digest",return_value="d"*64),\
             patch.object(M.WHOLE,"verified_version",return_value=(
                 {"rows_in_overlay":22191},{},self.stages)),\
             patch.object(M.WHOLE.versioner,"MODULE",self.root),\
             patch.object(M.WHOLE.versioner,"safe_stage_path",side_effect=lambda p:p),\
             patch.object(M.PRE.KEYS,"verified_existing_plan",return_value=({},{})),\
             patch.object(M.PRE,"verify_mixed_stage",return_value=(
                 {},self.expected,self.source_file,self.mixed_manifest,
                 self.version["mixed_stage_parquet_sha256"],self.mixed_rows,self.mixed_safe)):
            result=M.snapshot(self.root,self.version["version_sha256"],
                self.mixed_safe,None,None,None,None,None,
                folder,fresh,safe,fast_bounded=True)
            gate.assert_called_once()
        self.assertEqual(result["total_h5_only_candidate_rows"],22274)
        self.assertEqual(result["candidate_year_rows"],{"2016":1,"2026":22273})
        self.assertFalse(result["purchased_parquet_historical_rows_included"])
        self.assertFalse(result["candidate_source_units_certified"])
        self.assertTrue(safe.exists())
        with patch.object(V,"MODULE",self.root),\
             patch.object(V,"ROOT",folder.parent),\
             patch.object(V,"REPORTS",self.reports),\
             patch.object(V.STAGER,"MODULE",self.root):
            verified=V.verify(safe,final)
        self.assertEqual(verified["total_h5_only_day_candidates_verified"],22274)
        self.assertEqual(verified["mixed_date_candidate_rows_verified"],83)
        self.assertFalse(verified["full_purchased_parquet_historical_market_included"])
        self.assertFalse(verified["original_market_source_freshness_rechecked"])

    def test_tampered_private_partition_rejected_without_success_safe(self):
        source=self.reports/"materialized.json"
        if not source.exists():
            self.skipTest("full roundtrip test must run first")
        out=self.reports/"tamper-check.json"
        with patch.object(V,"MODULE",self.root),\
             patch.object(V,"ROOT",self.root/"work"/"unified_parquet"/"candidate_snapshots"),\
             patch.object(V,"REPORTS",self.reports):
            data=json.loads(source.read_bytes())
            file=self.root/data["snapshot_relative_dir"]/"year=2016"/"day.parquet"
            original=file.read_bytes()
            try:
                file.write_bytes(original+b"corrupt")
                with self.assertRaisesRegex(ValueError,"missing/changed"):
                    V.verify(source,out)
            finally:
                file.write_bytes(original)
        self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
