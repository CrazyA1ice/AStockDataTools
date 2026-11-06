"""Independent full 1990..2010 private day audit: 21 fictional Parquet years.

Fixtures reside in temporary directories, with fake immutable-source state
proofs. Never opens the user's original H5, purchased Parquet or staging work.
"""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "independent_full_1990_2010_private_h5_audit_contract",
    HERE.parent/"tools"/"audit-original-h5-pre2011-private-21-year-day-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Full21YearPrivateH5ReadOnlyAuditTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.module=self.base/"fake-research"
        self.parent=self.module/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
        self.parent.mkdir(parents=True)
        self.root=self.base/"orig-market"
        self.root.mkdir()
        self.patches=[]
        audit={(y):(2,1,1,1) for y in range(1991,2011)}
        for p in (
            patch.object(M,"MODULE",self.module),
            patch.object(M,"PARENT",self.parent),
            patch.dict(M.ANNUAL.EXPECTED,audit,clear=True),
            patch.object(M.P90,"EXPECT_A_STOCKDAYS",2),
            patch.object(M.P90,"EXPECT_OTHER_STOCKDAYS",1),
            patch.object(M.P90,"EXPECT_A_SYMBOLS",1),
            patch.object(M.P90,"EXPECT_A_DATES",1),
            patch.object(M,"EXPECTED_ALL_STOCKDAYS",42),
            patch.object(M,"EXPECTED_ALL_OTHER",21),
            patch.object(M,"_source_gate",return_value=("a"*64,"b"*64)),
        ):
            p.start();self.patches.append(p)
        self.folders={}
        for year in range(1990,2011):
            self.write_year(year)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def write_year(self,year,*,one_timestamp=None,source=None,ohlc=None,symbol=None):
        relative=f"work/unified_parquet/historical_pre2011_daily_pilots/{year}-research-{'a'*16}"
        folder=self.module/relative
        folder.mkdir(parents=True,exist_ok=True)
        self.folders[year]=folder
        stamp=one_timestamp if one_timestamp is not None else int(
            datetime(year,1,2,tzinfo=M.P90.CORE.UTC8).timestamp()*1000)
        source=source if source is not None else M.SOURCES[year]
        price={"open":10.0,"high":11.0,"low":9.0,"close":10.5,
               "volume":100.0,"amount":2000.0}
        if ohlc is not None:price.update(ohlc)
        data=[
            {"ts":stamp,"symbol":symbol or "600000.XSHG",
             **price,"source":source}
            for _ in range(2)
        ]
        # Two different symbol keys with the same date; synthetic one-day
        # source inventory must certify two candidate symbols, not one.
        data[1]["symbol"]="600001.XSHG" if symbol is None else symbol
        table=pa.Table.from_pylist(data,schema=M.ANNUAL._candidate_schema())
        parquet=folder/"day.parquet"
        pq.write_table(table,parquet,compression="snappy")
        if year==1990:
            fmt="AStockDataTools isolated uncertified 1990 H5 candidate day private v1"
        else:
            fmt=M.ANNUAL.FORMAT
        info={
            "format":fmt,"state":"verified_private_candidate_not_promoted",
            "year":year,"period":"day",
            "candidate_stockday_rows":2,
            "other_code_source_rows_not_staged":1,
            "distinct_source_dates":1,
            "market_candidate_rows":{"SH":2},
            "h5_original_state_sha256":"a"*64,
            "purchased_original_state_sha256":"b"*64,
            "private_parquet_written":True,
            "private_parquet_row_count":2,
            "private_parquet_sha256":M.P90._digest(parquet),
            "private_stage_relative_dir":relative,
            "candidate_price_factor":0.001,
            "candidate_volume_factor":100,
            "candidate_amount_factor":1000,
            **{k:False for k in M.ALWAYS_FALSE},
        }
        if year==1990:
            info["purchased_pre2011_absent_in_all_24_original_day_files"]=True
            info["h5_1990_source_exact_key_and_OHLCVA_geometry_passed"]=True
        else:
            info["purchased_pre2011_all_day_files_confirmed_absent"]=True
            info["native_day_keys_and_OHLCVA_geometry_checked"]=True
        (folder/"manifest.json").write_text(
            json.dumps(info,sort_keys=True),encoding="utf-8")
        return info

    def _update_content(self,year,mutate):
        path=self.folders[year]/"day.parquet"
        rows=pq.read_table(path).to_pylist()
        mutate(rows)
        table=pa.Table.from_pylist(rows,schema=M.ANNUAL._candidate_schema())
        pq.write_table(table,path,compression="snappy")
        f=self.folders[year]/"manifest.json"
        proof=json.loads(f.read_text("utf-8"))
        proof["private_parquet_sha256"]=M.P90._digest(path)
        f.write_text(json.dumps(proof,sort_keys=True),encoding="utf-8")

    def _audit(self):
        with redirect_stdout(StringIO()) as out:
            result=M.audit(self.root)
        return result,out.getvalue()

    def test_all_21_years_full_content_sha_exact_rows_and_no_writes(self):
        before={y:(f/"day.parquet").stat().st_mtime_ns
                for y,f in self.folders.items()}
        result,report=self._audit()
        self.assertEqual(result["years_verified"],21)
        self.assertEqual(result["private_a_code_stockday_rows_verified"],42)
        self.assertEqual(result["other_code_source_rows_excluded"],21)
        self.assertTrue(result["all_annual_candidate_keys_unique_and_year_bound"])
        self.assertTrue(result["all_annual_private_parquet_sha256_valid"])
        self.assertFalse(result["production_activated"])
        self.assertFalse(result["historical_security_master_certified"])
        self.assertFalse(result["h5_price_volume_amount_units_certified"])
        self.assertFalse(result["private_candidate_files_modified"])
        self.assertEqual(report.count("READONLY_PRIVATE_H5_YEAR_PASS="),21)
        self.assertNotIn("600000.XSHG",report)
        self.assertEqual(before,{y:(f/"day.parquet").stat().st_mtime_ns
                                 for y,f in self.folders.items()})

    def test_missing_annual_directory_refused(self):
        import shutil
        shutil.rmtree(self.folders[2006])
        with self.assertRaisesRegex(ValueError,"Not exactly 21"):
            self._audit()

    def test_extra_annual_directory_refused(self):
        (self.parent/"extra-private-year").mkdir()
        with self.assertRaisesRegex(ValueError,"Not exactly 21"):
            self._audit()

    def test_duplicate_or_wrong_symbol_rejected_even_with_updated_sha(self):
        self._update_content(1995,lambda rows:rows[1].update(symbol=rows[0]["symbol"]))
        with self.assertRaisesRegex(ValueError,"duplicate exact stockday"):
            self._audit()

    def test_out_of_year_timestamp_rejected_with_updated_sha(self):
        bad=int(datetime(2000,1,2,tzinfo=M.P90.CORE.UTC8).timestamp()*1000)
        self._update_content(1996,lambda rows:rows[1].update(ts=bad))
        with self.assertRaisesRegex(ValueError,"outside original native day year"):
            self._audit()

    def test_nonmidnight_timestamp_rejected_with_updated_sha(self):
        self._update_content(1997,lambda rows:rows[1].update(ts=rows[1]["ts"]+1000))
        with self.assertRaisesRegex(ValueError,"geometric sanity"):
            self._audit()

    def test_negative_volume_rejected_with_updated_sha(self):
        self._update_content(1998,lambda rows:rows[1].update(volume=-1.0))
        with self.assertRaisesRegex(ValueError,"geometric sanity"):
            self._audit()

    def test_wrong_original_h5_source_label_rejected_with_updated_sha(self):
        self._update_content(2000,lambda rows:rows[1].update(source="other_source"))
        with self.assertRaisesRegex(ValueError,"provenance source label"):
            self._audit()

    def test_private_parquet_byte_sha_change_rejected(self):
        path=self.folders[2001]/"day.parquet"
        path.write_bytes(path.read_bytes()+b"mutated")
        with self.assertRaisesRegex(ValueError,"content SHA256 mismatch"):
            self._audit()

    def test_1990_source_proof_flag_must_be_true(self):
        f=self.folders[1990]/"manifest.json"
        obj=json.loads(f.read_text("utf-8"))
        obj["purchased_pre2011_absent_in_all_24_original_day_files"]=False
        f.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"1990 original H5/PQ"):
            self._audit()

    def test_production_merge_and_unit_certification_never_assumed(self):
        for key in ("ready_for_production_merge",
                    "h5_volume_amount_price_units_certified"):
            with self.subTest(key=key):
                f=self.folders[2005]/"manifest.json"
                info=json.loads(f.read_text("utf-8"))
                info[key]=True
                f.write_text(json.dumps(info),encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"uncertified gate"):
                    self._audit()
                info[key]=False
                f.write_text(json.dumps(info),encoding="utf-8")

    def test_source_stat_drift_after_21_year_verification_fails(self):
        with patch.object(M,"_source_gate",side_effect=[
            ("a"*64,"b"*64),("e"*64,"b"*64)]):
            with self.assertRaisesRegex(ValueError,"changed during 21-year audit"):
                self._audit()

    def test_wrong_original_security_pattern_rejected_with_updated_sha(self):
        self._update_content(2004,lambda rows:rows[1].update(symbol="INVALID.XSHG"))
        with self.assertRaisesRegex(ValueError,"noncanonical stock code"):
            self._audit()

    def test_annual_count_manifest_mismatch_fails_before_private_scan(self):
        f=self.folders[2010]/"manifest.json"
        obj=json.loads(f.read_text("utf-8"))
        obj["candidate_stockday_rows"]=3
        f.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"uncertified gate"):
            self._audit()


if __name__=="__main__":
    unittest.main(verbosity=2)
