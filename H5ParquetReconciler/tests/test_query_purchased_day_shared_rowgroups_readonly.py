"""Purchased Parquet shared daily RowGroup batch: synthetic physical Arrow tests."""
import importlib.util
import tempfile
import unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE.parent/"tools"/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

M=load("shared_purchased_rowgroup_batch_tests",
       "query-purchased-day-shared-rowgroups-readonly.py")
JOIN=load("shared_purchased_indexed_join_tests",
          "query-private-purchased-plus-22274-candidates.py")
SYMS=("SH600000","SH600519")
FIRST="2026-09-30"
LAST="2026-10-13"


def stamp(d):
    return int(datetime.fromisoformat(d+"T00:00:00+08:00").timestamp()*1000)


def data(sym,day):
    return {"ts":stamp(day),"symbol":sym,
            "open":10.0,"high":11.0,"low":9.0,"close":10.5,
            "volume":100.0,"amount":1000.0}


class SharedPhysicalRowsTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        tmp=tempfile.TemporaryDirectory(prefix="shared_purchased_day_",dir=scratch)
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.source=self.root/"purchased.parquet"
        fields=[pa.field("ts",pa.int64()),pa.field("symbol",pa.string())]
        fields += [pa.field(f,pa.float64()) for f in M.P.validator.FIELDS]
        self.schema=pa.schema(fields)
        self.rows=[data(SYMS[0],FIRST),data(SYMS[1],FIRST)]
        self.store(self.rows)
        self.calls=[]

    def store(self,rows):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(rows,schema=self.schema),self.source,
                       row_group_size=1000)

    def preflight(self,root,sym,period,first,last,*args,**kwargs):
        import pyarrow.parquet as pq
        self.calls.append(sym)
        self.assertEqual((period,first,last),("day",FIRST,LAST))
        return {
            "symbol":sym,"period":"day","start":date(2026,9,30),
            "end":date(2026,10,13),
            "aliases":{sym},"pending":[(self.source,pq.ParquetFile(self.source),0)],
        }

    def run_shared(self,**options):
        with patch.object(M.P,"prepare_query",side_effect=self.preflight):
            return M.query_bars(self.root,SYMS,FIRST,LAST,**options)

    def test_two_symbols_share_one_physical_rowgroup_and_values_unchanged(self):
        result=self.run_shared()
        safe=result["safe_summary"]
        self.assertEqual(safe["shared_physical_candidate_rowgroups"],1)
        self.assertEqual(safe["shared_physical_source_rows_scanned"],2)
        self.assertEqual(safe["total_matching_purchased_rows"],2)
        self.assertEqual(set(result["bars_by_symbol"]),set(SYMS))
        self.assertEqual(result["bars_by_symbol"][SYMS[0]][0]["close"],10.5)
        self.assertEqual(result["bars_by_symbol"][SYMS[1]][0]["amount"],1000.0)
        self.assertFalse(safe["original_market_files_written"])
        self.assertFalse(safe["purchased_values_modified"])
        self.assertEqual(self.calls,list(SYMS))

    def test_bounded_source_capacity_counts_unique_physical_rowgroup_once(self):
        result=self.run_shared(max_candidate_rows_per_symbol=2,
                               max_total_candidate_rows=2)
        self.assertEqual(result["safe_summary"]["shared_physical_source_rows_scanned"],2)

    def test_budget_under_shared_rowgroup_rejected_before_read(self):
        with self.assertRaisesRegex(ValueError,"before scan"):
            self.run_shared(max_total_candidate_rows=1)

    def test_duplicate_purchased_symbol_timestamp_rejected(self):
        self.store([data(SYMS[0],FIRST),data(SYMS[0],FIRST)])
        with self.assertRaisesRegex(ValueError,"Duplicate purchased stock timestamp"):
            self.run_shared()

    def test_invalid_price_geometry_fails_closed(self):
        wrong=data(SYMS[0],FIRST)
        wrong["high"]=1.0
        self.store([wrong,data(SYMS[1],FIRST)])
        with self.assertRaisesRegex(ValueError,"OHLCVA geometry"):
            self.run_shared()

    def test_invalid_source_timestamp_fails_closed(self):
        wrong=data(SYMS[0],FIRST)
        wrong["ts"]+=1
        self.store([wrong,data(SYMS[1],FIRST)])
        with self.assertRaisesRegex(ValueError,"timestamp"):
            self.run_shared()

    def test_result_bars_per_symbol_budget_fails_closed(self):
        self.store([data(SYMS[0],FIRST),data(SYMS[0],"2026-10-08"),
                    data(SYMS[1],FIRST)])
        with self.assertRaisesRegex(ValueError,"per-symbol result-row limit"):
            self.run_shared(max_result_bars_per_symbol=1)

    def test_total_batch_result_budget_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"total result-row limit"):
            self.run_shared(max_total_result_bars=1)

    def test_exact_source_spelling_unknown_stock_ignored(self):
        self.store([data(SYMS[0],FIRST),data("SH688888",FIRST),
                    data(SYMS[1],FIRST)])
        r=self.run_shared()
        self.assertEqual(r["safe_summary"]["shared_physical_source_rows_scanned"],3)
        self.assertEqual(r["safe_summary"]["total_matching_purchased_rows"],2)

    def test_bounded_query_empty_file_has_no_purchased_values(self):
        self.store([data("SH688888",FIRST)])
        r=self.run_shared()
        self.assertEqual(sum(map(len,r["bars_by_symbol"].values())),0)
        self.assertEqual(r["safe_summary"]["shared_physical_source_rows_scanned"],1)

    def test_duplicate_explicit_symbol_rejected(self):
        with self.assertRaisesRegex(ValueError,"unique stocks"):
            M.query_bars(self.root,["SH600000","SH600000"],FIRST,LAST)

    def test_bad_candidate_budget_flag_rejected(self):
        with self.assertRaisesRegex(ValueError,"bounded"):
            M.query_bars(self.root,list(SYMS),FIRST,LAST,
                         max_total_candidate_rows=0)

    def test_shared_query_selected_source_only_h5_never_opened(self):
        r=self.run_shared()
        self.assertTrue(r["safe_summary"]["original_h5_opened"] is False)
        self.assertEqual(r["safe_summary"]["requested_stock_count"],2)

    def test_default_join_mode_still_unmodified(self):
        import inspect
        sig=inspect.signature(JOIN.query)
        self.assertIs(sig.parameters["purchased_shared_rowgroups"].default,False)
        self.assertIs(sig.parameters["index_safe"].default,None)


if __name__=="__main__":
    unittest.main(verbosity=2)
