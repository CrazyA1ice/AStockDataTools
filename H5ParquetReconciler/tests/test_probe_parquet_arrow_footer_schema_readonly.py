"""Only synthetic PyArrow files. Never opens licensed Parquet/H5/SQLite."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "parquet_schema_footer_under_test",
    HERE.parent/"tools"/"probe-parquet-arrow-footer-schema-readonly.py")
P=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def prior_unknown():
    windows=[]
    for symbol in ("SH600000","SZ000001"):
        for day in ("2026-08-24","2026-09-30"):
            windows.append({
                "symbol":symbol,"date":day,"day_rows":1,
                "min5_rows":48,"min1_rows":241,"closed_session":False,
                "time_grid_checked":True,"same_adjustment_basis":False,
                "day_vs_5min_amount_relative_gap":"0.000000025",
                "day_vs_1min_amount_relative_gap":"0.000000025",
                "day_vs_5min_volume_relative_gap":"0",
                "day_vs_1min_volume_relative_gap":"0",
            })
    return {
        "format":P.AUDIT.FORMAT,
        "sanitized_aggregates_only":True,
        "no_raw_market_rows":True,
        "independent_unit_reference":"none",
        "schemas":{p:{
            "date_type":"unknown","price_type":"unknown",
            "amount_type":"unknown","volume_type":"unknown",
            "timezone":"unknown","amount_unit_declared":"unknown",
            "volume_unit_declared":"unknown"} for p in P.PERIODS},
        "windows":windows,
    }


class FooterSchemaOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"fictional_parquet_source"
        self.root.mkdir()
        self.files={}
        for name in P.PERIODS:
            folder=self.root/name
            folder.mkdir()
            filename=folder/"2026-09.parquet"
            self.files[name]=filename
        self.reports=Path(self.tmp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.prior=self.reports/"prior-sanitized.json"
        self.prior.write_text(json.dumps(prior_unknown()),encoding="utf-8")
        self.out=self.reports/"schema-safe.json"
        self.enriched=self.reports/"enriched-safe.json"
        self.assessed=self.reports/"assessed-safe.json"
        p=patch.object(P.AUDIT,"REPORTS",self.reports)
        p.start()
        self.addCleanup(p.stop)

    def _write_parquet(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from decimal import Decimal
        schema=pa.schema([
            ("datetime",pa.timestamp("ns",tz="Asia/Shanghai")),
            ("open",pa.float64()),("high",pa.float64()),
            ("low",pa.float64()),("close",pa.float64()),
            ("amount",pa.decimal128(18,2)),
            ("volume",pa.int64()),
            ("private_arbitrary_column",pa.string()),
        ],metadata={b"user_path":b"C:/Users/PRIVATE/paid_market.parquet"})
        arrays=[
            pa.array([0,1],type=pa.int64()).cast(
                pa.timestamp("ns",tz="Asia/Shanghai")),
            *(pa.array([10.,12.],type=pa.float64()) for _ in range(4)),
            pa.array([Decimal("10.00"),Decimal("13.11")],
                     type=pa.decimal128(18,2)),
            pa.array([100,200],type=pa.int64()),
            pa.array(["do-not-emit-private","private-value"],type=pa.string())
        ]
        tab=pa.Table.from_arrays(arrays,schema=schema)
        for file in self.files.values():
            pq.write_table(tab,file,compression="zstd")

    def _run(self,reader=None):
        return P.probe(
            self.root,"day/2026-09.parquet","5min/2026-09.parquet",
            "1min/2026-09.parquet",self.prior,
            self.out,self.enriched,self.assessed,reader=reader)

    def test_real_synthetic_parquet_footer_only_matches_arrow_schema(self):
        try:
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable; footer-only integration not run")
        self._write_parquet()
        hashes={p:P.footer_guard(path) for p,path in self.files.items()}
        with patch.object(pq,"read_table",
                          side_effect=AssertionError("must not read rows")):
            info,assessment=self._run()
        self.assertTrue(info["footer_only_no_row_data_loaded"])
        self.assertTrue(info["sources_read_only"])
        self.assertEqual(set(info["periods"]),set(P.PERIODS))
        for period,details in info["periods"].items():
            self.assertTrue(details["parquet_metadata_only"])
            self.assertEqual(details["row_group_count"],1)
            self.assertEqual(details["total_source_rows_from_footer"],2)
            self.assertTrue(all(details["recognized_alias_presence"].values()))
            self.assertEqual(details["audit_schema"],{
                "date_type":"timestamp_ns","price_type":"float64",
                "amount_type":"decimal128","volume_type":"int64",
                "timezone":"Asia/Shanghai","amount_unit_declared":"unknown",
                "volume_unit_declared":"unknown",
            })
        self.assertEqual({p:P.footer_guard(path) for p,path in self.files.items()},
                         hashes)
        self.assertFalse(assessment["ready_to_plan_independent_unit_check"])
        self.assertFalse(assessment["ready_for_full_market_mirror"])
        saved=self.enriched.read_text(encoding="utf-8")
        self.assertIn('"timestamp_ns"',saved)
        self.assertIn('"amount_unit_declared": "unknown"',saved)
        self.assertEqual(
            json.loads(saved)["windows"],prior_unknown()["windows"])
        for report in (self.out,self.enriched,self.assessed):
            text=report.read_text(encoding="utf-8")
            for secret in ("PRIVATE","private_arbitrary_column",
                           "do-not-emit-private","2026-09.parquet",
                           "C:/Users","private-value"):
                self.assertNotIn(secret,text)

    def test_only_explicit_relative_period_parquet_files_selected(self):
        self._write_parquet()
        self.assertEqual(P.selected_file(self.root,"day/2026-09.parquet","day"),
                         self.files["day"])
        for relative in ("/tmp/source.parquet","../2026-09.parquet",
                         "5min/2026-09.parquet","day/../../x.parquet",
                         "day/abc.csv","day/other/file.parquet"):
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError,"one safe period"):
                    P.selected_file(self.root,relative,"day")
        with self.assertRaisesRegex(ValueError,"ABSOLUTE"):
            P.selected_file(Path("relative"),"day/2026-09.parquet","day")

    def test_symlinked_market_file_or_folder_rejected(self):
        self._write_parquet()
        alias=self.root/"day"/"alias.parquet"
        try:
            alias.symlink_to(self.files["day"])
        except (OSError,NotImplementedError):
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaisesRegex(ValueError,"existing plain file"):
            P.selected_file(self.root,"day/alias.parquet","day")

    def test_footer_magic_and_footer_budget_guard(self):
        file=self.files["day"]
        file.write_bytes(b"not a parquet file")
        with self.assertRaisesRegex(ValueError,"magic"):
            P.footer_guard(file)
        file.write_bytes(b"PAR1"+b"x"*16+(1024*1024+1).to_bytes(4,"little")+b"PAR1")
        with self.assertRaisesRegex(ValueError,"bounded budget"):
            P.footer_guard(file,max_footer=1024)

    def test_no_data_row_read_or_query_execution_in_code(self):
        import inspect
        code=inspect.getsource(P.inspect_footer)
        self.assertIn("pq.ParquetFile",code)
        self.assertIn("reader.schema_arrow",code)
        self.assertIn("reader.metadata",code)
        self.assertIn("reader.close()",code)
        for forbidden in ("read_row_group(","read_table(","iter_batches(",
                          "scanner(","read_column("):
            # Comments describe forbidden functions, check callable code only.
            lines=[line for line in code.splitlines()
                   if line.strip() and not line.lstrip().startswith("#")]
            self.assertFalse(any(forbidden in l for l in lines))

    def test_schema_unknown_for_integer_date_and_nonwhitelisted_alias(self):
        import pyarrow as pa
        schema=pa.schema([
            ("date",pa.int64()),("open",pa.int32()),
            ("high",pa.int32()),("low",pa.int32()),
            ("close",pa.int32()),("amount",pa.uint64()),
            ("volume",pa.uint32())])
        info=P.canonical_schema(schema,pa)
        self.assertEqual(info["audit_schema"]["date_type"],"unknown")
        self.assertEqual(info["audit_schema"]["timezone"],"unknown")
        self.assertEqual(info["audit_schema"]["price_type"],"unknown")
        self.assertEqual(info["audit_schema"]["amount_type"],"uint64")
        self.assertEqual(info["audit_schema"]["volume_type"],"unknown")

    def test_multiple_date_aliases_are_ambiguous_not_arbitrarily_selected(self):
        import pyarrow as pa
        schema=pa.schema([
            ("date",pa.timestamp("ms",tz="UTC")),
            ("datetime",pa.timestamp("ns",tz="Asia/Shanghai")),
            ("open",pa.float64()),("high",pa.float64()),
            ("low",pa.float64()),("close",pa.float64())])
        info=P.canonical_schema(schema,pa)
        self.assertEqual(info["audit_schema"]["date_type"],"unknown")
        self.assertEqual(info["audit_schema"]["timezone"],"unknown")
        self.assertEqual(info["ambiguous_alias_roles"],["date"])

    def test_unapproved_timezone_is_unknown_not_silently_normalized(self):
        import pyarrow as pa
        t=pa.timestamp("us",tz="Asia/Tokyo")
        schema=pa.schema([("datetime",t)])
        info=P.canonical_schema(schema,pa)
        self.assertEqual(info["audit_schema"]["date_type"],"timestamp_us")
        self.assertEqual(info["audit_schema"]["timezone"],"unknown")

    def test_never_guess_physical_units_even_with_complete_typed_schema(self):
        info={
            p:{"audit_schema":{
                "date_type":"timestamp_ns","price_type":"float64",
                "amount_type":"decimal128","volume_type":"int64",
                "timezone":"Asia/Shanghai","amount_unit_declared":"unknown",
                "volume_unit_declared":"unknown"}}
            for p in P.PERIODS}
        doc,result=P.enrich_existing_sanitized(prior_unknown(),info)
        self.assertEqual(doc["independent_unit_reference"],"none")
        self.assertFalse(result["amount_physical_unit_certified"])
        self.assertFalse(result["volume_physical_unit_certified"])
        self.assertFalse(result["licensed_parquet_to_h5_mapping_certified"])
        self.assertIn("closed_session_time_grid_or_adjustment_unproven",
                      result["evidence_blockers"])

    def test_existing_sanitized_claims_or_extra_raw_data_fail_closed(self):
        src=prior_unknown()
        src["raw_market_ohlcva"]=[{"close":10.11}]
        with self.assertRaisesRegex(ValueError,"Unexpected evidence"):
            P.enrich_existing_sanitized(src,{})
        src=prior_unknown()
        src["schemas"]["day"]["date_type"]="timestamp_ns"
        with self.assertRaisesRegex(ValueError,"original unknown"):
            P.enrich_existing_sanitized(src,{})

    def test_reports_cannot_be_overwritten_or_written_outside_module(self):
        self._write_parquet()
        self.out.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self._run()
        self.assertEqual(self.out.read_text(encoding="utf-8"),"protected")
        self.out.unlink()
        other=Path(self.tmp.name)/"outside.json"
        with self.assertRaisesRegex(ValueError,"direct non-symlink"):
            P.probe(self.root,"day/2026-09.parquet",
                    "5min/2026-09.parquet","1min/2026-09.parquet",
                    self.prior,other,self.enriched,self.assessed)

    def test_failed_input_schema_check_prevents_any_source_file_read(self):
        self._write_parquet()
        bad=json.loads(self.prior.read_text(encoding="utf-8"))
        bad["raw_rows"]=[{"amount":123}]
        self.prior.write_text(json.dumps(bad),encoding="utf-8")
        with patch.object(P,"inspect_footer",
                          side_effect=AssertionError("unsafe footer executed")):
            with self.assertRaisesRegex(ValueError,"Unexpected evidence"):
                self._run()
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
