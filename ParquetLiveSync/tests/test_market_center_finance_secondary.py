"""Bounded synthetic validation for the real secondary financial source pilot."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import unittest

import market_finance_secondary as S


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows
        self.index = list(range(len(rows)))

    def to_dict(self, *, orient):
        if orient != "records":
            raise AssertionError("Unexpected data shape")
        return list(self.rows)


class FakeAk:
    def __init__(self):
        self.announcements = {
            "财务报告": [
                {"代码": "000010", "公告日期": "2026-11-20",
                 "公告标题": "2026年第三季度报告", "公告类型": "财务报告"},
                {"代码": "600519", "公告日期": "2026-11-19",
                 "公告标题": "2026年报", "公告类型": "财务报告"},
            ],
            "信息变更": [
                {"代码": "000010", "公告日期": "2026-11-21",
                 "公告标题": "2026年第三季度报告更正公告",
                 "公告类型": "信息变更"},
            ],
            "持股变动": [],
        }
        self.calls = []
        self.balance = [
            {"REPORT_DATE": "2026-09-30", "NOTICE_DATE": "2026-10-25",
             "TOTAL_ASSETS": 1000, "TOTAL_LIABILITIES": 400,
             "TOTAL_EQUITY": 600},
        ]
        self.income = [
            {"REPORT_DATE": "2026-09-30", "NOTICE_DATE": "2026-10-25",
             "TOTAL_OPERATE_INCOME": 1200, "PARENT_NETPROFIT": 110},
        ]
        self.cash = [
            {"REPORT_DATE": "2026-09-30", "NOTICE_DATE": "2026-10-25",
             "NETCASH_OPERATE": 50},
        ]

    def stock_notice_report(self, *, report_type, recent_page):
        self.calls.append(("notice", report_type, recent_page))
        return FakeFrame(self.announcements[report_type])

    def stock_balance_sheet_by_report_em(self, *, symbol):
        self.calls.append(("balance", symbol))
        return FakeFrame(self.balance)

    def stock_profit_sheet_by_report_em(self, *, symbol):
        self.calls.append(("income", symbol))
        return FakeFrame(self.income)

    def stock_cash_flow_sheet_by_report_em(self, *, symbol):
        self.calls.append(("cash", symbol))
        return FakeFrame(self.cash)


def synthetic_stock_root(folder):
    """Mimic the eight-period directory contract using only temporary paths."""
    root = Path(folder)
    for period in S.E.L.PERIODS:
        (root / "AllCycleAStockData" / period).mkdir(parents=True, exist_ok=True)
    return root


class FinanceSecondaryTests(TestCase):
    def test_recent_financial_and_correction_candidates_have_stable_identity(self):
        ak = FakeAk()
        d = S.discover_recent(
            ak, observed_on=date(2026, 11, 22), days=7, pages=2,
            known_symbols=["000010.SZ"])
        self.assertEqual(d["unique_event_leads"], 3)
        self.assertEqual(d["candidate_symbols_in_known_scope"], ["000010.SZ"])
        self.assertFalse(d["feed_complete_for_date_range"])
        self.assertFalse(d["can_schedule_download"])
        self.assertFalse(d["can_commit"])
        self.assertTrue(any(e["kind"] == "CORRECTION_CANDIDATE"
                            for e in d["events_sample"]))
        self.assertEqual(ak.calls, [
            ("notice", "财务报告", "2"), ("notice", "信息变更", "2"),
            ("notice", "持股变动", "2"),
        ])

    def test_modern_akshare_date_based_notice_api_is_supported(self):
        class ModernAk(FakeAk):
            def stock_notice_report(self, *, symbol, date):
                self.calls.append(("modern", symbol, date))
                if date == "20261121":
                    return FakeFrame(self.announcements[symbol])
                return FakeFrame([])
        ak = ModernAk()
        d = S.discover_recent(
            ak, observed_on=date(2026, 11, 22), days=3,
            known_symbols=["000010.SZ"])
        self.assertEqual(d["query_strategy"], "MODERN_BY_DATE")
        self.assertEqual(d["source_requests_attempted"], 9)
        self.assertEqual(d["candidate_symbols_in_known_scope"], ["000010.SZ"])
        self.assertEqual(len(ak.calls), 9)
        self.assertEqual(ak.calls[0], ("modern", "财务报告", "20261122"))
        self.assertFalse(d["can_schedule_download"])

    def test_partial_announcement_query_failure_not_no_new_reports(self):
        class ModernAk(FakeAk):
            def stock_notice_report(self, *, symbol, date):
                if symbol == "信息变更":
                    raise ConnectionError("request failed")
                return FakeFrame(self.announcements[symbol] if
                                 date == "20261121" else [])
        d = S.discover_recent(
            ModernAk(), observed_on=date(2026, 11, 22),
            days=2, known_symbols=["000010.SZ"])
        self.assertEqual(d["status"], "RECENT_LEADS_PARTIAL_SOURCE_ERROR")
        self.assertEqual(len(d["failed_categories"]), 2)
        self.assertFalse(d["empty_means_no_financial_updates"])
        self.assertFalse(d["feed_complete_for_date_range"])

    def test_qmt_report_date_supports_14_digits_and_millisecond_epoch(self):
        self.assertEqual(S._day("20260930000000"), "2026-09-30")
        self.assertEqual(S._day("20260930"), "2026-09-30")
        self.assertEqual(S._day("1790697600000"), "2026-09-30")

    def test_unknown_stock_suffix_never_guessed_from_six_digits(self):
        d = S.discover_recent(FakeAk(), observed_on=date(2026, 11, 22),
                              known_symbols=["000010.SH", "000010.SZ"])
        self.assertEqual(d["candidate_symbols_in_known_scope"], [])
        self.assertGreater(d["unresolved_identity_leads"], 0)

    def test_bad_source_dates_are_ignored_and_future_dates_not_used(self):
        ak = FakeAk()
        ak.announcements["财务报告"] = [
            {"代码": "000010", "公告日期": "2026-11-23",
             "公告标题": "future"},
            {"代码": "000010", "公告日期": "garbled",
             "公告标题": "bad date"},
        ]
        d = S.discover_recent(ak, observed_on=date(2026, 11, 22),
                              known_symbols=["000010.SZ"])
        self.assertEqual(d["unique_event_leads"], 1)
        self.assertEqual(d["candidate_symbols_in_known_scope"], ["000010.SZ"])

    def test_total_assets_net_profit_and_cash_flow_values_compare(self):
        ak = FakeAk()
        qmt = {
            "Balance": [
                {"m_timetag": "20260930", "tot_assets": 1000,
                 "tot_liab": 400, "total_equity": 600}],
            "Income": [
                {"m_timetag": "20260930", "revenue": 1200,
                 "net_profit_excl_min_int_inc": 110}],
            "CashFlow": [
                {"m_timetag": "20260930", "net_cash_flows_oper_act": 50}],
        }
        with TemporaryDirectory() as folder, \
             patch.object(S.I, "_latest_snapshot_day",
                          return_value="2026-11-21"), \
             patch.object(S.E, "_financial_snapshot_rows",
                          side_effect=lambda _x, _c, table, _d: qmt[table]):
            r = S.crosscheck_saved(synthetic_stock_root(folder), "000010.SZ", ak)
        self.assertEqual(r["fields_compared"], 6)
        self.assertEqual(r["fields_inconclusive"], 0)
        self.assertEqual(r["fields_attempted"], 6)
        self.assertEqual(r["value_differences"], 0)
        self.assertEqual([t["report_dates_in_both"] for t in r["tables"]],
                         [1, 1, 1])
        self.assertFalse(r["can_clear_pending"])
        self.assertFalse(r["can_commit"])
        self.assertEqual([call[1] for call in ak.calls],
                         ["SZ000010"] * 3)

    def test_true_numeric_difference_is_preserved_as_review_only(self):
        result = S.compare_rows(
            "Balance", [{"m_timetag": "20260930", "tot_assets": 100}],
            [{"REPORT_DATE": "2026-09-30", "TOTAL_ASSETS": 105}])
        self.assertEqual(result["status_counts"]["VALUE_DIFFERENCE"], 1)
        self.assertFalse(result["can_resolve_historical_pending"])

    def test_duplicate_historical_variant_not_silently_selected(self):
        r = S.compare_rows(
            "Income", [
                {"m_timetag": "20260930", "revenue": 100},
                {"m_timetag": "20260930", "revenue": 200}],
            [{"REPORT_DATE": "2026-09-30", "TOTAL_OPERATE_INCOME": 100}],
        )
        self.assertIn(
            "NOT_COMPARABLE_OR_REVISION_AMBIGUOUS", r["status_counts"])
        self.assertEqual(r["fields_comparable"], 0)
        self.assertGreater(r["fields_inconclusive"], 0)

    def test_missing_external_columns_are_not_reported_as_agreement(self):
        result = S.compare_rows(
            "Balance", [{"m_timetag": "20260930", "tot_assets": 123}],
            [{"REPORT_DATE": "2026-09-30"}])
        self.assertEqual(result["comparison_count"], 3)
        self.assertEqual(result["fields_comparable"], 0)
        self.assertEqual(result["fields_inconclusive"], 3)
        self.assertNotIn("EXACT_MATCH", result["status_counts"])

    def test_no_common_report_date_is_not_a_clean_comparison(self):
        result = S.compare_rows(
            "Balance", [{"m_timetag": "20260930", "tot_assets": 123}],
            [{"REPORT_DATE": "2026-06-30", "TOTAL_ASSETS": 123}])
        self.assertEqual(result["report_dates_in_both"], 0)
        self.assertEqual(result["fields_comparable"], 0)
        self.assertEqual(result["comparison_count"], 0)

    def test_crosscheck_rejects_missing_real_layout_instead_of_bypassing_guard(self):
        with TemporaryDirectory() as folder, \
             self.assertRaisesRegex(ValueError, "AllCycleAStockData"):
            S.crosscheck_saved(Path(folder), "000010.SZ", FakeAk())

    def test_missing_qmt_snapshot_does_not_mean_provider_missing(self):
        with TemporaryDirectory() as folder, \
             patch.object(S.I, "_latest_snapshot_day", return_value=None):
            r = S.crosscheck_saved(synthetic_stock_root(folder), "000010.SZ", FakeAk())
        self.assertTrue(all(t["status"] == "NO_LOCAL_QMT_SNAPSHOT"
                            for t in r["tables"]))
        self.assertEqual(r["fields_compared"], 0)

    def test_provider_failure_is_explicit_and_cannot_greenlight_history(self):
        ak = FakeAk()
        def broken(*, symbol):
            raise RuntimeError("provider error")
        ak.stock_profit_sheet_by_report_em = broken
        rows = [{"m_timetag": "20260930", "tot_assets": 1000}]
        with TemporaryDirectory() as folder, \
             patch.object(S.I, "_latest_snapshot_day",
                          return_value="2026-11-21"), \
             patch.object(S.E, "_financial_snapshot_rows",
                          return_value=rows):
            r = S.crosscheck_saved(synthetic_stock_root(folder), "000010.SZ", ak)
        self.assertIn("EXTERNAL_SOURCE_ERROR",
                      [t["status"] for t in r["tables"]])
        self.assertFalse(r["can_commit"])

    def test_pilot_only_returns_candidates_not_approved_downloads(self):
        ak = FakeAk()
        with TemporaryDirectory() as folder, \
             patch.object(S.I, "_latest_snapshot_day", return_value=None):
            r = S.pilot(Path(folder), ["000010.SZ"], ak,
                        observed_on=date(2026, 11, 22))
        self.assertEqual(r["status"], "EXTERNAL_FINANCE_PILOT_REVIEW_ONLY")
        self.assertEqual(r["discovery"]["candidate_symbols_in_known_scope"],
                         ["000010.SZ"])
        self.assertEqual(r["event_candidates_to_download"], [])
        self.assertFalse(r["can_apply"])
        self.assertFalse(r["changed_pending"])
        self.assertFalse(r["changed_20_05_task"])

    def test_absence_of_akshare_or_invalid_window_is_not_faked_as_empty(self):
        with self.assertRaises(S.SecondarySourceBlocked):
            S.discover_recent(FakeAk(), observed_on=date(2026, 11, 22),
                              days=0)
        with self.assertRaises(S.SecondarySourceBlocked):
            S.pilot(Path("C:/not-real"), ["000010.SZ"] * 4, FakeAk(),
                    observed_on=date(2026, 11, 22))


if __name__ == "__main__":
    unittest.main()
