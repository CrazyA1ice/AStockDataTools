"""Synthetic offline fail-closed tests, no real QMT, Parquet engine, or network."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

BASE = Path(__file__).resolve().parent.parent


def load(module_name, file):
    spec = importlib.util.spec_from_file_location(module_name, BASE / file)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


P = load("pinned_versioned_preview", "qmt_finance_versioned_recovery_preview.py")
D = load("pinned_002188_pilot", "qmt_finance_002188_pinned_review_once.py")


class E:
    FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital",
                  "Top10FlowHolder", "Top10Holder", "HolderNum",
                  "PershareIndex", "PerShare")

    @staticmethod
    def canonical_json(value):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _path_check(path):
        return None

    @staticmethod
    def _financial_snapshot_file(root, code, table, day):
        target = (Path(root) / "financial" / table / code / "snapshots" /
                  (day + "-" + "0"*16 + ".parquet"))
        return target if target.is_file() else None

    @staticmethod
    def _financial_snapshot_rows(root, code, table, day):
        target = E._financial_snapshot_file(root, code, table, day)
        return json.loads(target.read_text(encoding="utf-8")) if target else None


class F:
    E = E

    @staticmethod
    def _rows(records):
        return Counter(E.canonical_json({k: v for k, v in row.items()
                                         if k != "_index"}) for row in records)

    @staticmethod
    def _prior_rows(root, code, table):
        folder = Path(root) / "financial" / table / code / "snapshots"
        days = sorted({item.name[:10] for item in folder.glob("*.parquet")})
        values = Counter()
        for day in days:
            values |= F._rows(E._financial_snapshot_rows(root, code, table, day))
        return (days[-1], values) if days else (None, None)


def holder(k, *, period="20200930", serial="0"):
    return {"endDate": period, "name": "Holder no " + str(k),
            "shares": k + 100, "_index": serial}


def raw(row):
    return E.canonical_json({k: v for k, v in row.items() if k != "_index"})


def capital(period, quarter, amount=50):
    return {"m_timetag": period, "m_quarter": quarter,
            "total_capital": amount}


def tiny_fixture():
    a, b, c = holder(1), holder(2), holder(3)
    old = Counter({raw(a): 2, raw(b): 2, raw(c): 1})
    current = [dict(a, _index="0"), dict(a, _index="1"),
               dict(b, _index="2"), dict(b, _index="3"),
               dict(c, _index="4")]
    hashes = frozenset((P.digest(raw(a)), P.digest(raw(b))))
    union_digest = P.digest(E.canonical_json(sorted(old.items())))
    return old, current, hashes, union_digest


def check(prior, current, hashes, union, distinct=3, extra=2):
    return P._check_pinned_002188_multiset(
        prior, current, F, expected_raw_sha256=hashes,
        expected_union_sha256=union, expected_distinct=distinct,
        expected_extra=extra)


class MultisetPureTests(unittest.TestCase):
    def test_exact_duplicates_preserve_every_occurrence(self):
        old, current, hashes, digest = tiny_fixture()
        rows, proof = check(old, current, hashes, digest)
        self.assertEqual(len(rows), 5)
        self.assertEqual(proof["verified_repeated_raw_groups"], 2)
        self.assertEqual(proof["verified_extra_occurrences"], 2)
        self.assertEqual(proof["historical_and_current_total_rows"], 5)
        self.assertFalse(proof["allow_deduplication"])
        self.assertFalse(proof["allow_apply"])
        self.assertFalse(proof["allow_pending_clear"])

    def test_current_duplicate_row_removed_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "QMT_CACHE_MULTIPLICITY_CHANGED"):
            check(old, current[:-2] + [current[-1]], hashes, digest)

    def test_current_duplicate_extra_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "QMT_CACHE_MULTIPLICITY_CHANGED"):
            check(old, current + [current[0]], hashes, digest)

    def test_unrelated_business_value_change_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        current[0]["shares"] += 5
        with self.assertRaisesRegex(P.ReviewBlocked, "QMT_CACHE_MULTIPLICITY_CHANGED"):
            check(old, current, hashes, digest)

    def test_one_missing_historical_hash_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        missing = frozenset(list(sorted(hashes))[:1])
        with self.assertRaisesRegex(P.ReviewBlocked, "DUPLICATE_HASH_SET_CHANGED"):
            check(old, current, missing, digest)

    def test_injected_unlisted_duplicate_hash_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        extra = set(hashes)
        extra.add("0" * 64)
        with self.assertRaisesRegex(P.ReviewBlocked, "DUPLICATE_HASH_SET_CHANGED"):
            check(old, current, frozenset(extra), digest)

    def test_invalid_union_fingerprint_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "HISTORY_UNION_CHANGED"):
            check(old, current, hashes, "0" * 64)

    def test_wrong_distinct_count_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "MULTIPLICITY_COUNT_DRIFT"):
            check(old, current, hashes, digest, distinct=4)

    def test_wrong_extra_count_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "MULTIPLICITY_COUNT_DRIFT"):
            check(old, current, hashes, digest, extra=1)

    def test_duplicate_of_other_report_period_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        parsed = json.loads(next(iter(old)))
        parsed["endDate"] = "20211231"
        changed = E.canonical_json(parsed)
        old[changed] = old.pop(next(iter(old)))
        with self.assertRaisesRegex(P.ReviewBlocked, "DUPLICATE_REPORT_PERIOD_DRIFT"):
            check(old, current, hashes, digest)

    def test_historical_triple_copy_is_not_accepted(self):
        old, current, hashes, digest = tiny_fixture()
        old[next(iter(old))] = 3
        with self.assertRaisesRegex(P.ReviewBlocked, "OUT_OF_SCOPE"):
            check(old, current, hashes, digest, extra=3)

    def test_historical_noninteger_copy_count_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        old[next(iter(old))] = True
        with self.assertRaises(P.ReviewBlocked):
            check(old, current, hashes, digest, extra=1)

    def test_invalid_json_blocks(self):
        old, current, hashes, digest = tiny_fixture()
        old["NOT_JSON"] = 1
        old.pop(next(iter(old)))
        with self.assertRaisesRegex(P.ReviewBlocked, "INVALID_JSON"):
            check(old, current, hashes, digest)

    def test_source_names_are_not_exposed_by_proof(self):
        old, current, hashes, digest = tiny_fixture()
        _, proof = check(old, current, hashes, digest)
        self.assertNotIn("Holder no", json.dumps(proof))

    def test_review_proof_deterministic_under_reordering(self):
        old, current, hashes, digest = tiny_fixture()
        _, x = check(old, current, hashes, digest)
        _, y = check(Counter(reversed(list(old.items()))), list(reversed(current)),
                     hashes, digest)
        self.assertEqual(x, y)

    def test_no_generic_duplicate_waiver(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "HISTORICAL_DUPLICATE_OR_MALFORMED"):
            P._historical(old, F)

    def test_pinned_002188_requires_exact_real_ledger(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "AUDIT_LEDGER_CHANGED"):
            P._pinned_002188_historical(old, current, F, {}, "0" * 64)

    def test_pinned_002188_requires_real_manifest(self):
        old, current, hashes, digest = tiny_fixture()
        with self.assertRaisesRegex(P.ReviewBlocked, "EVIDENCE_NOT_EXACT"):
            P._pinned_002188_historical(
                old, current, F, {}, P.PINNED_002188_LEDGER_SHA256)


class PilotEpochTests(unittest.TestCase):
    def test_time_guard(self):
        tz = timezone(timedelta(hours=8))
        with self.assertRaisesRegex(RuntimeError, "NIGHTLY_TASK_WINDOW"):
            D.protect_clock(datetime(2026, 11, 25, 20, 5, tzinfo=tz))
        D.protect_clock(datetime(2026, 11, 25, 12, 58, tzinfo=tz))

    def test_pilot_ledger_id_required(self):
        state = {
            "format": "qmt_financial_cache_import_v1",
            "daily_date": D.LEDGER_DATE, "root": "test",
            "pending": {
                D.CODE: {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Capital"},
                "688259.SH": {"reason": "CACHE_DECODE_ERROR"},
            },
        }
        for i in range(52):
            state["pending"]["9{:05d}.SZ".format(i)] = {
                "reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Top10Holder"}
        D.validate_ledger(state, D.LEDGER_SHA)
        with self.assertRaisesRegex(RuntimeError, "LEDGER_DRIFT"):
            D.validate_ledger(state, "f" * 64)
        state["pending"][D.CODE]["detail"] = "table=HolderNum"
        with self.assertRaisesRegex(RuntimeError, "PENDING_SCOPE_CHANGED"):
            D.validate_ledger(state, D.LEDGER_SHA)

    def test_original_pins_are_nine_real_64_char_sha256(self):
        self.assertEqual(len(P.PINNED_002188_RAW_SHA256), 9)
        self.assertTrue(all(len(x) == 64 for x in P.PINNED_002188_RAW_SHA256))
        self.assertEqual(sorted(P.PINNED_002188_SNAPSHOTS), ["2026-11-17", "2026-11-18"])
        self.assertEqual(P.PINNED_002188_UNION_SHA256,
                         "664618c29fbdc510fc2155c0657a8cb8c843be45c0e5bfa2affa68f364756359")

    def test_manifest_false_write_and_dedup_flags(self):
        doc = {"format": "qmt_002188_top10holder_exact_multiplicity_pin_v1"}
        with self.assertRaisesRegex(RuntimeError, "MANIFEST_MISMATCH"):
            D.prepare_evidence(doc, P)

    def test_snapshot_set_must_match_exact_days(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / "financial" / D.HOLDER_TABLE / D.CODE / "snapshots"
            folder.mkdir(parents=True)
            (folder / ("2026-11-17-" + "0"*16 + ".parquet")).write_text("fake")
            with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_DATES_CHANGED"):
                D.check_selected_holder_files(root, E, F, P)


if __name__ == "__main__":
    unittest.main()
