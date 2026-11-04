"""Two bounded synthetic proofs: original minute H5 tail and purchased Parquet
footer max; never inspect any real market price or stock identifiers.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"
spec=importlib.util.spec_from_file_location(
    "real_minute_source_end_fixture",
    TOOLS/"probe-original-minute-source-ends-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

class OriginalMinuteSourceEndOnlyTests(unittest.TestCase):
    def setUp(self):
        work=HERE.parent/"work"
        work.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix="source-end-",
                                              dir=work)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_only_first_and_last_native_h5_timestamps_aggregated(self):
        import h5py
        import numpy as np
        d=self.root/"HikyuuData"
        d.mkdir()
        with h5py.File(d/"sh_1min.h5","w") as h:
            group=h.create_group("data")
            dt=np.dtype([("datetime","<u8"),("closePrice","<u4")])
            for code,labels in (
                ("SH600000",[202610091501,202610121500]),
                ("SH600001",[202610091500,202610131500]),
            ):
                arr=np.zeros(len(labels),dtype=dt)
                arr["datetime"]=labels
                arr["closePrice"]=[1,2]
                group.create_dataset(code,data=arr)
        r=M.h5_bounds(self.root,"1min","sh")
        self.assertEqual(r["native_tables_checked"],2)
        self.assertEqual(r["native_tables_with_rows"],2)
        self.assertEqual(r["max_of_stock_last_native_stamps"],202610131500)
        self.assertEqual(r["last_native_calendar_day"],"20261013")
        self.assertFalse(r["coverage_cutoff_proven"])
        self.assertNotIn("SH600000",str(r))
        self.assertFalse(M.h5_bounds(self.root,"5min","sh")[
            "source_file_present"])

    def test_purchased_year_footer_finds_max_without_price_scan(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        source=self.root/"purchased-2026.parquet"
        pq.write_table(pa.table({
            "ts":pa.array([1791855000000,1791941400000],type=pa.int64()),
            "symbol":pa.array(["000001.XSHE","000002.XSHE"]),
        }),source,row_group_size=1)
        with patch.object(M.CORE,"year_files",return_value=[source]):
            r=M.purchased_footer(self.root,"1min",2026)
        self.assertEqual(r["source_files"],1)
        self.assertEqual(r["total_rowgroups"],2)
        self.assertEqual(r["rowgroups_without_ts_statistics"],0)
        self.assertEqual(r["max_rowgroup_ts_ms"],1791941400000)
        self.assertTrue(r["rowgroup_bounds_cover_all_groups"])
        self.assertNotIn("000001.XSHE",str(r))
        self.assertFalse(r["source_coverage_certified"])

if __name__=="__main__":
    unittest.main(verbosity=2)
