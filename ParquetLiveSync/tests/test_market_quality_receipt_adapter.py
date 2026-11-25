"""Read-only generic daily receipt -> quality rules: actual disk fixtures only."""
from __future__ import annotations
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_quality_engine as Q
import market_quality_receipt_adapter as M


def fixture(root, day, *, accepted=3, bad=None):
    bad = bad if bad is not None else {
        "SH600036":"ValueError: Independent official DAY materialized OHLC discrepancy: open",
        "SZ300119":"ValueError: QMT returned no original OHLCVA 1m: 300119.SZ",
    }
    folder=Path(root)/"work"/"market_update"/"daily"
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(day+".parquet")
    payload=("safe-synthetic-candidate-"+day).encode()
    path.write_bytes(payload)
    doc={
        "format":M.FORMAT, "date":day,
        "sha256":sha256(payload).hexdigest(),
        "rows":accepted*240, "stock_days_accepted":accepted,
        "expected_stock_days":accepted+len(bad),
        "quarantined":bad,
        "source_family":"QMT_AND_TDX_OFFICIAL_DAY",
        "production_merge_authorized":False,
    }
    receipt=path.with_suffix(".json")
    receipt.write_text(json.dumps(doc,sort_keys=True),encoding="utf-8")
    return path,receipt,doc


class ReceiptAdapterTests(unittest.TestCase):
    def test_two_distant_days_classified_in_independent_bounded_windows(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2024-09-18")
            fixture(root,"2026-11-25",
                    bad={"BJ920021":"ValueError: QMT returned no original OHLCVA 1m"})
            a=M.classify_daily(root,start_day="2024-09-18",end_day="2024-09-18")
            b=M.classify_daily(root,start_day="2026-11-25",end_day="2026-11-25")
            self.assertEqual(a["existing_day_receipts_checked"],1)
            self.assertEqual(b["existing_day_receipts_checked"],1)
            self.assertEqual(a["producer_quarantines_preserved"],2)
            self.assertEqual(b["producer_quarantines_preserved"],1)
            self.assertEqual(b["quality_cases"]["cases"][0]["scope"]["symbol"],"BJ920021")
            self.assertFalse(a["production_merge_authorized"])
            self.assertFalse(b["official_day_source_independently_certified"])

    def test_cannot_fake_official_daily_universe_from_same_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-05-12")
            r=M.classify_daily(root,start_day="2025-05-12",end_day="2025-05-12")
            entries={c["scope"]["symbol"]:c for c in r["quality_cases"]["cases"]}
            miss=entries["SZ300119"]
            self.assertIn("PRODUCER_QUARANTINED",miss["detected_rules"])
            self.assertNotIn("MISSING_STOCK_DAY",miss["detected_rules"])
            self.assertIn("OFFICIAL_DAY_EVIDENCE_MISSING",miss["unverified_rules"])
            self.assertIsNone(miss["source_snapshot_sha256"])
            self.assertIsNone(miss["official_reference_sha256"])
            self.assertNotIn("source_sha256",r["quality_cases"])

    def test_open_error_is_only_one_producer_failed_field(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-05-12")
            r=M.classify_daily(root,start_day="2025-05-12",end_day="2025-05-12")
            entries={c["scope"]["symbol"]:c for c in r["quality_cases"]["cases"]}
            op=entries["SH600036"]
            self.assertIn("OHLCVA_MISMATCH",op["detected_rules"])
            self.assertIn("PRODUCER_QUARANTINED",op["detected_rules"])
            self.assertNotIn("INCOMPLETE_TIME_GRID",op["detected_rules"])
            self.assertEqual(op["quality_state"],"QUARANTINED")
            self.assertFalse(op["production_admission_authorized"])

    def test_unknown_reason_still_remains_quarantined(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2023-06-22",bad={"SH600000":"Other: unclassified producer condition"})
            r=M.classify_daily(root,start_day="2023-06-22",end_day="2023-06-22")
            row=r["quality_cases"]["cases"][0]
            self.assertIn("PRODUCER_QUARANTINED",row["detected_rules"])
            self.assertEqual(row["quality_state"],"QUARANTINED")
            self.assertFalse(r["data_quality_cleared"])

    def test_no_quarantine_receipt_is_not_production_certification(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-07-16",bad={})
            r=M.classify_daily(root,start_day="2025-07-16",end_day="2025-07-16")
            self.assertEqual(r["quality_cases"]["case_count"],0)
            self.assertFalse(r["production_merge_authorized"])
            self.assertFalse(r["official_day_source_independently_certified"])

    def test_receipt_and_candidate_parquet_physical_shas_are_checked(self):
        with tempfile.TemporaryDirectory() as root:
            parquet,receipt,doc=fixture(root,"2025-06-18")
            r=M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")
            meta=r["source_receipts"][0]
            self.assertEqual(meta["accepted_candidate_parquet_sha256"],doc["sha256"])
            self.assertEqual(meta["producer_receipt_bytes_sha256"],sha256(receipt.read_bytes()).hexdigest())
            self.assertFalse(meta["quarantined_raw_qmt_sha_verified"])
            self.assertFalse(meta["official_day_reference_independently_verified"])

    def test_byte_change_in_candidate_refused(self):
        with tempfile.TemporaryDirectory() as root:
            parquet,_,_=fixture(root,"2025-06-18")
            parquet.write_bytes(b"corrupted")
            with self.assertRaisesRegex(M.AdapterError,"SHA_CHANGED"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_missing_candidate_pair_refused(self):
        with tempfile.TemporaryDirectory() as root:
            parquet,_,_=fixture(root,"2025-06-18")
            parquet.unlink()
            with self.assertRaisesRegex(M.AdapterError,"INPUT_MISSING"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_accepted_quarantine_counts_must_reconcile(self):
        with tempfile.TemporaryDirectory() as root:
            _,receipt,doc=fixture(root,"2025-06-18")
            doc["expected_stock_days"]+=1
            receipt.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(M.AdapterError,"QUARANTINE_COUNT"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_rows_have_exact_240_per_accepted_stock(self):
        with tempfile.TemporaryDirectory() as root:
            _,receipt,doc=fixture(root,"2025-06-18")
            doc["rows"]=999
            receipt.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(M.AdapterError,"STOCK_COUNTS"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_producer_write_permission_must_remain_false(self):
        with tempfile.TemporaryDirectory() as root:
            _,receipt,doc=fixture(root,"2025-06-18")
            doc["production_merge_authorized"]=True
            receipt.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(M.AdapterError,"SOURCE_OR_PERMISSION"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_unknown_source_family_refused(self):
        with tempfile.TemporaryDirectory() as root:
            _,receipt,doc=fixture(root,"2025-06-18")
            doc["source_family"]="untrusted unknown"
            receipt.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(M.AdapterError,"SOURCE_OR_PERMISSION"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_invalid_quarantine_symbol_refused(self):
        with tempfile.TemporaryDirectory() as root:
            _,receipt,doc=fixture(root,"2025-06-18",
                                  bad={"not-a-stock":"ValueError: failed"})
            receipt.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(M.AdapterError,"QUARANTINE_INVALID"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_duplicate_json_object_key_refused(self):
        with tempfile.TemporaryDirectory() as root:
            _,receipt,_=fixture(root,"2025-06-18")
            text=receipt.read_text(encoding="utf-8")
            text=text.replace('"format":', '"format":"bad", "format":',1)
            receipt.write_text(text,encoding="utf-8")
            with self.assertRaisesRegex(M.AdapterError,"RECEIPT_JSON_INVALID"):
                M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")

    def test_range_restriction_prevents_unbounded_scan(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-01-10")
            with self.assertRaisesRegex(M.AdapterError,"OVERSIZE_DATE_RANGE"):
                M.classify_daily(root,start_day="2025-01-01",end_day="2025-12-31")

    def test_no_existing_receipt_in_selected_window_is_review_required(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-01-10")
            with self.assertRaisesRegex(M.AdapterError,"NO_VERIFIABLE_RECEIPTS"):
                M.classify_daily(root,start_day="2025-01-13",end_day="2025-01-13")

    def test_does_not_infer_missing_calendar_days_between_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-03-03")
            fixture(root,"2025-03-05")
            r=M.classify_daily(root,start_day="2025-03-03",end_day="2025-03-05")
            self.assertEqual(r["existing_day_receipts_checked"],2)
            self.assertEqual(r["producer_quarantines_preserved"],4)
            self.assertNotIn("2025-03-04",[x["day"] for x in r["source_receipts"]])

    def test_real_file_bytes_unmodified_after_readonly_scan(self):
        with tempfile.TemporaryDirectory() as root:
            p,rec,_=fixture(root,"2025-06-18")
            x,y=p.read_bytes(),rec.read_bytes()
            before={str(t) for t in Path(root).rglob("*")}
            M.classify_daily(root,start_day="2025-06-18",end_day="2025-06-18")
            after={str(t) for t in Path(root).rglob("*")}
            self.assertEqual(before,after)
            self.assertEqual(x,p.read_bytes())
            self.assertEqual(y,rec.read_bytes())

    def test_cli_success_on_selected_date_with_no_qmt(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root,"2025-06-18")
            output=StringIO()
            with redirect_stdout(output):
                code=M.main(["--module-root",root,"--start-day","2025-06-18",
                             "--end-day","2025-06-18"])
            self.assertEqual(code,0)
            doc=json.loads(output.getvalue())
            self.assertEqual(doc["status"],M.STATUS)
            self.assertFalse(doc["qmt_cache_write_authorized"])

    def test_cli_invalid_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            output=StringIO()
            with redirect_stdout(output):
                code=M.main(["--module-root",root,"--start-day","2025-06-18",
                             "--end-day","2025-06-18"])
            self.assertEqual(code,3)
            self.assertIn("REVIEW_REQUIRED",output.getvalue())

    def test_has_no_provider_import_or_production_write_dependency(self):
        import inspect
        src=inspect.getsource(M)
        self.assertNotIn("from xtquant",src)
        self.assertNotIn("download_history_data(",src)
        self.assertNotIn("pq.write_table(",src)
        self.assertNotIn("os.replace(",src)


if __name__=="__main__":unittest.main()
