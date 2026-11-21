"""S4: all-nine-table pure precommit review, no downloads or market writes."""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import json
import unittest

import market_scoped_finance_history_review as R
import qmt_extra_data as E


def row(value, **other):
    return {"_index": "0", "m_timetag": value, **other}


def payload(stock="000001.SZ", *, missing=False):
    present = {} if missing else {
        stock: {t: [] for t in E.FIN_TABLES}
    }
    counts = {} if missing else {
        stock: {t: 0 for t in E.FIN_TABLES}
    }
    return {
        "format": "qmt_financial_cache_batch_v1",
        "mode": "daily", "symbols": [stock],
        "refresh_start": "20261120", "refresh_end": "20261120",
        "records": present,
        "missing_symbols": [stock] if missing else [],
        "row_counts": counts,
    }


def planning(_extra, _stock, _asof, data):
    planned = {
        name: {"action": "CREATE_VERSION" if data[name] else "UNCHANGED"}
        for name in E.FIN_TABLES
    }
    staged = {t: data[t] for t in E.FIN_TABLES if data[t]}
    return planned, staged


def no_previous(_extra, _stock, _table):
    return None, Counter()


class ReadonlyHistoryGateTests(unittest.TestCase):
    def check(self, doc, **kwargs):
        return R.evaluate(
            doc, stocks=["000001.SZ"], start="20261120",
            end="20261120", extra=Path("UNUSED"),
            asof="2026-11-21", prior=no_previous,
            planner=planning, **kwargs)

    def test_new_version_candidate_is_not_commit_permission(self):
        p = payload()
        p["records"]["000001.SZ"]["Capital"] = [row("20260930")]
        p["row_counts"]["000001.SZ"]["Capital"] = 1
        result = self.check(p)
        self.assertEqual(result["stocks_candidate_for_review"], 1)
        self.assertEqual(result["stock_results"][0]["tables_checked"], 9)
        self.assertFalse(result["can_commit"])
        self.assertEqual(result["official_market_writes"], 0)
        self.assertFalse(result["multisource_verified"])

    def test_real_importer_planner_runs_without_any_write(self):
        p = payload()
        p["records"]["000001.SZ"]["Capital"] = [row("20260930")]
        p["row_counts"]["000001.SZ"]["Capital"] = 1
        with patch.object(R.I, "_prior_rows", side_effect=no_previous), \
             patch.object(R.I, "_commit_symbol") as persist, \
             patch.object(R.I, "_save_state") as ledger:
            output = R.evaluate(
                p, stocks=["000001.SZ"], start="20261120",
                end="20261120", extra=Path("UNUSED"),
                asof="2026-11-21", prior=no_previous,
                planner=R.I._plan_symbol)
        persist.assert_not_called()
        ledger.assert_not_called()
        self.assertEqual(output["stock_results"][0]["table_actions"][
            "CREATE_VERSION"], 1)
        self.assertFalse(output["can_commit"])

    def test_all_nine_tables_are_reported_when_two_historical_conflicts(self):
        p = payload()
        p["records"]["000001.SZ"]["Capital"] = [row("20260930")]
        p["row_counts"]["000001.SZ"]["Capital"] = 1
        called = []
        def prior(_extra, _stock, table):
            called.append(table)
            if table in ("Capital", "HolderNum"):
                return "2026-11-17", Counter({
                    E.canonical_json(
                        {"m_timetag": "20260630", "revision": table}): 1})
            return None, Counter()
        with patch.object(R.I, "_plan_symbol") as planner:
            result = R.evaluate(
                p, stocks=["000001.SZ"], start="20261120",
                end="20261120", extra=Path("UNUSED"),
                asof="2026-11-21", prior=prior,
                planner=planner)
        self.assertEqual(len(called), 9)
        self.assertEqual(result["stocks_history_conflict"], 1)
        self.assertEqual({x["table"] for x in
                          result["stock_results"][0]["historical_conflicts"]},
                         {"Capital", "HolderNum"})
        planner.assert_not_called()
        self.assertFalse(result["can_commit"])

    def test_missing_cache_is_not_marked_healthy(self):
        result = self.check(payload(missing=True))
        self.assertEqual(result["stocks_missing_cache"], 1)
        self.assertEqual(result["stock_results"][0]["tables_checked"], 0)
        self.assertFalse(result["all_nine_tables_locally_compared"])

    def test_incomplete_table_set_is_rejected(self):
        p = payload()
        del p["records"]["000001.SZ"]["Balance"]
        with self.assertRaisesRegex(R.PrecommitBlocked,
                                    "NINE_FINANCIAL_TABLES"):
            self.check(p)

    def test_row_count_mismatch_is_rejected(self):
        p = payload()
        p["records"]["000001.SZ"]["Income"] = [row("20260930")]
        with self.assertRaisesRegex(R.PrecommitBlocked, "TABLE_SHAPE"):
            self.check(p)

    def test_invalid_index_is_rejected(self):
        p = payload()
        p["records"]["000001.SZ"]["Income"] = [
            {"_index": 0, "m_timetag": "20260930"}]
        p["row_counts"]["000001.SZ"]["Income"] = 1
        with self.assertRaisesRegex(R.PrecommitBlocked, "TABLE_SHAPE"):
            self.check(p)

    def test_wrong_announcement_window_rejected(self):
        p = payload()
        p["refresh_end"] = "20261119"
        with self.assertRaisesRegex(R.PrecommitBlocked, "ENVELOPE"):
            self.check(p)

    def test_invalid_calendar_date_in_worker_window_rejected(self):
        p = payload()
        p["refresh_start"] = "20261340"
        with self.assertRaisesRegex(R.PrecommitBlocked, "DATE_INVALID"):
            R.evaluate(
                p, stocks=["000001.SZ"], start="20261340",
                end="20261120", extra=Path("UNUSED"),
                asof="2026-11-21", prior=no_previous,
                planner=planning)

    def test_empty_nine_table_present_cache_is_not_candidate(self):
        result = self.check(payload())
        self.assertEqual(result["stocks_missing_cache"], 1)
        self.assertEqual(result["stocks_candidate_for_review"], 0)
        self.assertFalse(result["stock_results"][0]["can_commit"])

    def test_missing_and_present_overlap_rejected(self):
        p = payload()
        p["missing_symbols"].append("000001.SZ")
        with self.assertRaisesRegex(R.PrecommitBlocked, "COVERAGE"):
            self.check(p)

    def test_previous_historical_day_in_future_rejected(self):
        p = payload()
        with self.assertRaisesRegex(R.PrecommitBlocked, "SAVED_HISTORY"):
            R.evaluate(
                p, stocks=["000001.SZ"], start="20261120",
                end="20261120", extra=Path("UNUSED"),
                asof="2026-11-21",
                prior=lambda *a: ("2026-11-22", Counter()),
                planner=planning)

    def test_stock_scope_must_be_exact_sorted_unique(self):
        self.assertEqual(R._stock_scope("000001.SZ,600519.SH"),
                         ["000001.SZ", "600519.SH"])
        for invalid in (
            "600519.SH,000001.SZ",
            "000001.SZ,000001.SZ",
            "600519",
            ",".join(f"{n:06}.SZ" for n in range(1, 7)),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(R.PrecommitBlocked):
                    R._stock_scope(invalid)

    def test_private_stage_filename_and_uuid_directory_only(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "scoped-cache-stage" / ("a"*32) / "cache.json"
            good.parent.mkdir(parents=True)
            R._strict_stage(root, good)
            with self.assertRaisesRegex(R.PrecommitBlocked, "PRIVATE_JOB"):
                R._strict_stage(root, root / "cache.json")

    def test_invalid_ledger_or_cache_sha_rejected_before_read(self):
        with self.assertRaisesRegex(R.PrecommitBlocked, "SHA256"):
            R.review(
                root=Path("invalid"), workspace=Path("invalid"),
                cache_file=Path("invalid"), expected_cache_sha256="bad",
                expected_progress_sha256="a"*64,
                symbols="000001.SZ", start="20261120", end="20261120")

    def test_cli_requires_explicit_readonly_no_io(self):
        with patch.object(R, "review") as review:
            stream = io.StringIO()
            with redirect_stdout(stream):
                rc = R.main([
                    "--root", "D:/stock", "--workspace", "X",
                    "--cache-file", "X/cache.json",
                    "--expected-cache-sha256", "a"*64,
                    "--expected-progress-sha256", "b"*64,
                    "--symbols", "000001.SZ",
                    "--start", "20261120", "--end", "20261120"])
        self.assertEqual(rc, 2)
        review.assert_not_called()
        self.assertIn("OPTIN_REQUIRED", stream.getvalue())

    def test_windows_launcher_waits_for_review_and_does_not_import(self):
        text = (Path(__file__).resolve().parents[1] /
                "run-scoped-qmt-finance-cache.ps1").read_text(
                    encoding="utf-8-sig")
        self.assertIn("market_scoped_finance_history_review.py", text)
        self.assertIn("SCOPED_FINANCE_PRECOMMIT=", text)
        self.assertIn("WaitForExit(90000)", text)
        self.assertIn("CANONICAL_PARQUET_COMMIT=NO", text)
        self.assertIn("$report.can_commit -ne $false", text)
        self.assertIn("Local\\AStockDataTools2005AllStages", text)
        self.assertNotIn("qmt_extra_financial_cache_import.py", text)
        self.assertNotIn(" --apply", text.lower())


if __name__ == "__main__":
    unittest.main()
