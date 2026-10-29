"""Synthetic verified batch queries. No original market data or API access."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name, file):
    spec=importlib.util.spec_from_file_location(name,file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B=load("batch_private_day_query_test",HERE.parent/"tools"/
       "query-parquet-primary-day-overlay-batch-readonly.py")
F=load("batch_private_day_fixture",HERE/
       "test_build_parquet_primary_day_overlay.py")


@contextmanager
def prepared():
    with F.ready() as (root,module,report,gate,purchased,stage_dir,staged):
        plan=F.M.prepare(root,gate,report,[stage_dir])
        with patch.object(B.single,"versioner",F.M):
            yield root,module,report,gate,purchased,stage_dir,plan


def read(root,sha,symbols=("SH600000","SZ000001"),**options):
    return B.query_private_day_overlay_batch(
        root,list(symbols),"2026-09-30","2026-10-08",sha,**options)


class BatchDayOverlayReadOnlyTests(unittest.TestCase):
    def test_two_symbols_one_live_audit_one_stage_decode_and_no_source_writes(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            before=F.M.stage_tool.file_digest(purchased)
            live=F.M.stage_tool.verify_live_absence_dates
            verify=B.single.verified_version
            decode=B.selected_private_rows
            with patch.object(F.M.stage_tool,"verify_live_absence_dates",
                              wraps=live) as single_audit, \
                 patch.object(B.single,"verified_version",
                              wraps=verify) as single_verify, \
                 patch.object(B,"selected_private_rows",
                              wraps=decode) as single_decode:
                result=read(root,plan["version_sha256"])
            single_audit.assert_called_once()
            single_verify.assert_called_once()
            single_decode.assert_called_once()
            self.assertEqual(list(result["bars_by_symbol"]),
                             ["SH600000","SZ000001"])
            self.assertEqual([b["trading_date"] for b in
                              result["bars_by_symbol"]["SH600000"]],
                             ["2026-09-30","2026-10-08"])
            self.assertEqual([b["value_source"] for b in
                              result["bars_by_symbol"]["SH600000"]],
                             ["purchased_parquet",
                              "private_hikyuu_h5_gap_candidate"])
            self.assertEqual(result["bars_by_symbol"]["SZ000001"],[])
            safe=result["safe_summary"]
            self.assertEqual(safe["symbol_count"],2)
            self.assertEqual(safe["matching_bar_count"],2)
            self.assertEqual(safe["purchased_parquet_bars_returned"],1)
            self.assertEqual(safe["private_overlay_bars_returned"],1)
            self.assertEqual(safe["private_stage_verification_row_count"],1)
            self.assertEqual(safe["private_stage_rows_decoded_for_selected_dates"],1)
            self.assertEqual(safe["live_absence_recheck_scan_count"],1)
            self.assertTrue(safe["no_raw_ohlcva_in_safe_summary"])
            self.assertTrue(safe["no_production_query_switch"])
            self.assertFalse((module/"work"/"unified_parquet"/
                              "active-day-overlay.json").exists())
            self.assertNotIn('"open"',json.dumps(safe))
            self.assertEqual(F.M.stage_tool.file_digest(purchased),before)

    def test_invalid_duplicate_and_noncanonical_symbol_rejected_before_live_scan(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            with patch.object(F.M.stage_tool,"verify_live_absence_dates",
                              side_effect=AssertionError("must not scan")):
                for symbols in ([],["SH600000"]*2,["BAD"],
                                ["sh600000"],["SH600000"]*11):
                    with self.subTest(symbols=symbols):
                        with self.assertRaises(ValueError):
                            read(root,plan["version_sha256"],symbols=symbols)

    def test_purchase_source_arrival_on_private_day_rejects_entire_batch(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            target=purchased.parent/"2026-10.parquet"
            pq.write_table(pa.Table.from_pylist([{
                "ts":F.TEST_STAGE.stamp_ms(date(2026,10,8)),
                "symbol":"600000.XSHG",
                "open":12.3,"high":12.5,"low":12.2,
                "close":12.4,"volume":15000.0,
                "amount":1800000.0,"source":"new_purchased"
            }]),target)
            with self.assertRaisesRegex(ValueError,"Live source recheck"):
                read(root,plan["version_sha256"])

    def test_stage_tampering_is_rejected_before_batch_market_read(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            with (stage/"day.parquet").open("ab") as stream:
                stream.write(b"tampered-after-prepare")
            with patch.object(F.M.stage_tool,"verify_live_absence_dates",
                              side_effect=AssertionError("no live scan")):
                with self.assertRaisesRegex(ValueError,"bytes changed"):
                    read(root,plan["version_sha256"])

    def test_total_source_scan_budget_is_checked_per_stock(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            with self.assertRaisesRegex(ValueError,"budget exhausted"):
                read(root,plan["version_sha256"],
                     max_total_candidate_rows=1)

    def test_combined_total_bar_limit_rejects_without_partial_return(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            with self.assertRaisesRegex(ValueError,"total returned bars"):
                read(root,plan["version_sha256"],
                     max_total_result_bars=1)

    def test_baseline_only_batch_avoids_h5_live_scan(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            with patch.object(F.M.stage_tool,"verify_live_absence_dates",
                              side_effect=AssertionError("no selected H5 gap")):
                result=B.query_private_day_overlay_batch(
                    root,["SH600000","SZ000001"],
                    "2026-09-30","2026-09-30",
                    plan["version_sha256"])
            safe=result["safe_summary"]
            self.assertEqual(safe["live_absence_recheck_scan_count"],0)
            self.assertEqual(safe["matching_bar_count"],1)
            self.assertEqual(safe["private_overlay_bars_returned"],0)
            self.assertEqual(safe["private_stage_rows_decoded_for_selected_dates"],0)

    def test_missing_immutable_version_rejected(self):
        with prepared() as (root,module,report,gate,purchased,stage,plan):
            with self.assertRaisesRegex(ValueError,
                                        "Missing private immutable version"):
                read(root,"f"*64)


if __name__=="__main__":
    unittest.main(verbosity=2)
