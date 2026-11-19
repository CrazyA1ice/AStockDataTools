"""No-write readiness preflight restrictions; no local market data used."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audit_market_repair_preflight as R


class RepairReadinessTests(unittest.TestCase):
    def test_both_problem_stock_symbols_have_exact_vendor_aliases(self):
        self.assertEqual(R.vendor_symbols("SH688129"),
                         ["SH688129", "688129.SH", "688129.XSHG"])
        self.assertEqual(R.vendor_symbols("SZ300472"),
                         ["SZ300472", "300472.SZ", "300472.XSHE"])

    def test_repair_preflight_must_not_query_other_dates(self):
        with self.assertRaisesRegex(ValueError, "pinned to 2026-11-18"):
            R.inspect("D:/stock", "D:/ChatGPT/AStockDataTools",
                      date(2026, 11, 19))


if __name__ == "__main__":
    unittest.main()
