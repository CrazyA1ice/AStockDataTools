"""Metadata-only catalog: purchased source refs, highcycle SHA and safe private gap."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_eight_cycle_no_copy_catalog",
    HERE.parent/"tools"/"build-purchased-primary-eight-cycle-private-source-catalog.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

DAY="2026-10-08"
SYMS=("SH600000","SZ000001")
PERIODS=("15min","30min","60min")

def sha(data):
    return hashlib.sha256(data).hexdigest()

class PurchasedPrimarySourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.module=Path(self.t.name)/"H5ParquetReconciler"
        self.module.mkdir()
        self.market=Path(self.t.name)/"market"
        self.market.mkdir()
        self.purchased=self.market/"AllCycleAStockData"
        self.purchased.mkdir()
        self.stage=self.module/"work"/"unified_parquet"/"oct_high_cycle_staging"
        self.run=self.stage/"aaaaaaaaaaaa"
        self.run.mkdir(parents=True)
        self.daydir=self.module/"work"/"unified_parquet"/"minute_complete_day"
        self.daydir.mkdir(parents=True)
        self.sources={}
        self.files={}
        self._patches=[
            patch.object(M,"MODULE",self.module),
            patch.object(M.S,"MODULE",self.module),
            patch.object(M.S,"STAGE_ROOT",self.stage),
            patch.object(M,"DAYS",{DAY:2}),
            patch.object(M,"EXPECTED_STOCKDAYS",2),
            patch.object(M,"EXPECTED_HIGH_ROWS",56),
            patch.object(M.PRIVATE,"existing_stockdays",
                         return_value=(frozenset({(DAY,s) for s in SYMS}),1)),
            patch.object(M.MINUTE,"_safe_private_file",side_effect=self.minute_file),
            patch.object(M.FOOTER,"inventory",side_effect=self.footer_inventory),
            patch.object(M.FOOTER.F,"source_files",side_effect=self.source_files),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        for period,factor in (("15min",16),("30min",8),("60min",4)):
            path=self.run/(period+".parquet")
            path.write_bytes(("fake validated private "+period).encode())
            self.sources[period]=path
        self.receipt_doc={
            "source_days":[DAY],"symbols":list(SYMS),
            "verified_source_stockdays":2,
            "outputs":{period:{
                "private_file":self.sources[period].relative_to(self.module).as_posix(),
                "sha256":M._sha(self.sources[period]),
                "rows":2*factor,
                "complete_row_by_row_readback_exact":True}
                for period,factor in (("15min",16),("30min",8),("60min",4))}
        }
        (self.run/"receipt.json").write_text(
            json.dumps(self.receipt_doc),encoding="utf-8")
        for period in ("1min","5min"):
            path=self.daydir/(period+".parquet")
            path.write_bytes(("h5 complete validated source "+period).encode())
            self.files[period]=path
        for period in M.PERIODS:
            for year in M.YEARS:
                folder=self.purchased/period
                folder.mkdir(exist_ok=True)
                file=folder/(str(year)+".parquet")
                file.write_bytes(b"one original purchased Parquet reference")
        self.broken_minutes=False
        self.broken_footer=False

    def minute_file(self,d,period):
        self.assertEqual(d.isoformat(),DAY)
        if self.broken_minutes:
            return None
        return self.files[period],{
            "unified_parquet_sha256":M._sha(self.files[period]),
            "source_rows":{"h5_only_complete_stockday":240 if period=="1min" else 48},
        }

    def footer_inventory(self,root,years,**kw):
        self.assertEqual(tuple(years),M.YEARS)
        yearly={p:{str(y):{
            "source_files":1,
            "footer_envelope_complete_for_nonempty_row_groups":not self.broken_footer,
            "nonempty_row_groups_without_usable_ts_bounds":0,
            "row_groups_with_bounds_outside_filename_year":0,
            "source_rows_from_parquet_footers":100,
            "row_groups":1,
            "source_file_stat_identity_sha256_not_content_digest":"a"*64,
        } for y in M.YEARS} for p in M.PERIODS}
        return {
            "status":"read_only_purchased_parquet_footer_envelopes_not_exact_coverage",
            "only_original_parquet_file_footers_read":True,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "no_ohlcva_rows_read_or_exported":True,
            "requested_years":list(M.YEARS),
            "source_root_period_directories":list(M.PERIODS),
            "period_years":yearly,
        }

    def source_files(self,root,periods,first,last):
        self.assertEqual((first,last),(2011,2026))
        return {
            period:{year:[self.purchased/period/(str(year)+".parquet")]
                    for year in M.YEARS} for period in M.PERIODS
        },{
            "year_ambiguous_or_absent_parquet_filenames_by_period":{},
            "symlinked_parquet_files_skipped_by_period":{},
        }

    def test_assembles_eight_cycle_catalog_and_two_minute_refs_without_copies(self):
        result=M.assemble(self.market)
        self.assertEqual(result["status"],M.STATUS)
        self.assertEqual(len(result["periods"]),8)
        self.assertEqual(result["private_research_candidates"]["highcycle_total_candidate_rows"],56)
        self.assertEqual(result["private_research_candidates"]["stockdays_by_date"],{DAY:2})
        self.assertEqual(len(result["private_research_candidates"]["minute_h5_gap_private_references"]),2)
        self.assertEqual(len(result["purchased"]["original_source_files_by_period_year"]),128)
        self.assertFalse(result["ready_for_production_merge"])
        self.assertFalse(result["market_OHLCVA_read_or_copied_for_catalog"])
        self.assertFalse(result["vendor_units_certified"])
        self.assertFalse((self.module/"work"/"unified_parquet"/"source_catalog").exists())

    def test_immutable_catalog_write_and_idempotent_readback(self):
        sealed=M.seal(M.assemble(self.market))
        path,created=M.write_private_catalog(sealed)
        self.assertTrue(created)
        self.assertEqual(json.loads(path.read_text("utf-8")),sealed)
        again,created=M.write_private_catalog(sealed)
        self.assertEqual(again,path)
        self.assertFalse(created)
        self.assertEqual(path.read_bytes(),M._json(sealed))
        self.assertEqual(len(list(path.parent.glob("*.json"))),1)

    def test_purchased_stat_change_changes_catalog_version_without_copying(self):
        first=M.seal(M.assemble(self.market))["catalog_sha256"]
        source=self.purchased/"5min"/"2026.parquet"
        source.write_bytes(b"original Parquet file updated by EXTERNAL owner")
        second=M.seal(M.assemble(self.market))["catalog_sha256"]
        self.assertNotEqual(first,second)

    def test_altered_private_highcycle_sha_fails_before_catalog(self):
        self.sources["30min"].write_bytes(b"altered source")
        with self.assertRaisesRegex(ValueError,"SHA mismatch"):
            M.assemble(self.market)
        self.assertFalse((self.module/"work"/"unified_parquet"/"source_catalog").exists())

    def test_missing_private_minute_ref_blocks_catalog_version(self):
        self.broken_minutes=True
        with self.assertRaisesRegex(ValueError,"Missing verified private H5 minute"):
            M.assemble(self.market)

    def test_untrustworthy_purchased_footer_blocks_catalog(self):
        self.broken_footer=True
        with self.assertRaisesRegex(ValueError,"Incomplete purchased footer envelope"):
            M.assemble(self.market)

    def test_existing_catalog_tampering_fails_closed(self):
        sealed=M.seal(M.assemble(self.market))
        file,_=M.write_private_catalog(sealed)
        file.write_text("altered",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"content mismatch"):
            M.write_private_catalog(sealed)

if __name__=="__main__":
    unittest.main()
