"""Two source-independent tests of the actual 1990-2010 normalized
candidate/quarantine writer: no original H5 or purchased Parquet opened.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("synthetic_pre2011_normalized_candidates",
    HERE.parent/"tools"/"stage-pre2011-day-normalized-candidates-with-quarantine.py")
W=importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

def raw(day,vol,amt):
    return {"symbol":"SH600000","datetime":int(day.replace("-",""))*10000,
            "openPrice":10000,"highPrice":10000,"lowPrice":10000,
            "closePrice":10000,"transCount":vol,"transAmount":amt}

class Pre2011CandidateParquetTests(unittest.TestCase):
    def test_historical_vwap_candidate_never_promotes_wrong_units_or_zero_amount(self):
        good,reason=W.qualify(raw("1992-01-02",100,100),1992)
        self.assertIsNone(reason)
        self.assertEqual(good["open"],10.0)
        self.assertEqual(good["volume"],10000.0)
        self.assertEqual(good["amount"],100000.0)
        self.assertEqual(good["trading_date"],"1992-01-02")
        self.assertEqual(good["value_source"],W.SOURCE_KIND)
        self.assertTrue(W.SOURCE_KIND.endswith("not_vendor_certified"))
        self.assertEqual(W.qualify(raw("1992-01-03",100,10),1992)[1],
                         "alternative_historical_vwap_factor_100000")
        self.assertEqual(W.qualify(raw("1992-01-06",100,0),1992)[1],
                         "native_volume_or_amount_zero")
        with self.assertRaisesRegex(ValueError,"historical daily stamp"):
            W.qualify(raw("1992-01-02",100,100),1993)

    def test_real_synthetic_writing_keeps_native_bad_records_losslessly(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory(prefix="pre2011-candidate-") as tmp:
            base=Path(tmp)
            rawfile=base/"raw.parquet"
            rows=[raw("1992-01-02",100,100),raw("1992-01-03",100,10),
                  raw("1992-01-06",100,0)]
            pq.write_table(pa.Table.from_pylist(rows,schema=W.SINGLE.schema(pa)),
                           rawfile,row_group_size=2)
            sh=W.sha(rawfile)
            sources=[(y,rawfile,len(rows),sh) for y in range(1990,2011)]
            root=base/"work"/"unified_parquet"/"pre2011_day_candidates"
            reports=base/"reports"
            reports.mkdir()
            safe=reports/"day-candidates.json"
            with patch.object(W,"MODULE",base),patch.object(
                    W,"WORK",root),patch.object(
                    W,"REPORTS",reports),patch.object(
                    W.PROFILE,"source_safe",return_value=({"yearly":[]},"f"*64)),patch.object(
                    W.PROFILE,"verified_private_files",return_value=sources):
                result=W.annual(1992,base/"full21.json","123456789abc",safe)
                self.assertEqual(result["total_raw_h5_rows"],3)
                self.assertEqual(result["purchased_schema_candidate_rows_not_vendor_certified"],1)
                self.assertEqual(result["lossless_native_quarantine_rows"],2)
                self.assertFalse(result["ready_for_production_query"])
                good=base/result["candidate_parquet_relative_path"]
                bad=base/result["quarantine_parquet_relative_path"]
                with pq.ParquetFile(good) as p:
                    self.assertEqual(p.schema_arrow,W.PHYS.schema(pa))
                    self.assertEqual(p.metadata.num_rows,1)
                with pq.ParquetFile(bad) as p:
                    saved=p.read().to_pylist()
                    self.assertEqual(p.metadata.num_rows,2)
                    self.assertEqual(saved[0]["transAmount"],10)
                    self.assertEqual(saved[1]["transAmount"],0)
                self.assertEqual(json.loads(safe.read_text())["total_raw_h5_rows"],3)
                with self.assertRaisesRegex(ValueError,"Only new private"):
                    W.annual(1992,base/"full21.json","123456789abc",safe)

if __name__=="__main__":
    unittest.main(verbosity=2)
