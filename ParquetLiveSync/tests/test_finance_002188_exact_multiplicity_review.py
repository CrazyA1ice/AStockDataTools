"""Synthetic offline fail-closed tests, no real QMT, Parquet engine, or network."""
from collections import Counter
from datetime import datetime, timedelta, timezone
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
        source = next(iter(old))
        old["NOT_JSON"] = old.pop(source)
        with self.assertRaisesRegex(P.ReviewBlocked, "INVALID_JSON"):
            check(old, current, hashes, digest)

    def test_source_names_are_not_exposed_by_proof(self):
        old, current, hashes, digest = tiny_fixture()
        _, proof = check(old, current, hashes, digest)
        self.assertNotIn("Holder no", json.dumps(proof))

    def test_review_proof_deterministic_under_reordering(self):
        old, current, hashes, digest = tiny_fixture()
        _, x = check(old, current, hashes, digest)
        # Counter(iterable) counts tuple elements; build a mapping instead
        # so only iteration order changes, never the raw-row multiplicity.
        reordered = Counter(dict(reversed(list(old.items()))))
        self.assertEqual(reordered, old)
        self.assertEqual(list(reordered), list(reversed(old)))
        _, y = check(reordered, list(reversed(current)), hashes, digest)
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


class NineTablePinnedIntegrationTests(unittest.TestCase):
    """779/788 in-memory synthetic rows; Parquet filenames contain JSON fixtures."""

    def _fixture(self, root, *, missing_one_cache_repeat=False,
                 mutate_ledger_during_worker=False):
        import hashlib
        root = Path(root)
        private = root / "private"
        private.mkdir()
        ledger = root / "work" / "qmt_extra" / "financial-cache-progress.json"
        ledger.parent.mkdir(parents=True)
        pending = {
            D.CODE: {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Capital"},
            "688259.SH": {"reason": "CACHE_DECODE_ERROR"},
        }
        for i in range(52):
            pending["9{:05d}.SZ".format(i)] = {
                "reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Top10Holder"}
        ledger.write_text(json.dumps({
            "format": "qmt_financial_cache_import_v1",
            "root": str(private), "daily_date": D.LEDGER_DATE,
            "pending": pending,
        }), encoding="utf-8")

        holders = [holder(i, serial=str(i)) for i in range(779)]
        all_holders = holders + [
            dict(holders[i], _index=str(779 + i)) for i in range(9)]
        cache_holders = list(all_holders)
        if missing_one_cache_repeat:
            cache_holders.pop()
        old_capital = [capital(20200101 + i, 1, 50) for i in range(108)]
        old_capital += [capital(20200101 + i, 2, 50) for i in range(2)]
        new_capital = [dict(capital(20200101 + i, 1, 50),
                            _index=str(i)) for i in range(108)]
        new_capital.append(dict(capital(20261119, 3, 55), _index="108"))

        def store(table, day, rows):
            dest = private / "financial" / table / D.CODE / "snapshots"
            dest.mkdir(parents=True, exist_ok=True)
            p = dest / (day + "-" + "0"*16 + ".parquet")
            p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return p

        paths = {
            "2026-11-17": store("Top10Holder", "2026-11-17", holders),
            "2026-11-18": store("Top10Holder", "2026-11-18", all_holders),
        }
        store("Capital", "2026-11-17", old_capital)
        union = F._rows(all_holders)
        duplicates = frozenset(
            P.digest(raw_record) for raw_record, n in union.items() if n > 1)
        self.assertEqual((len(union), sum(union.values()), len(duplicates)),
                         (779, 788, 9))
        union_sha = P.digest(E.canonical_json(sorted(union.items())))
        snapshots = {}
        for day, p in paths.items():
            rows = E._financial_snapshot_rows(private, D.CODE, "Top10Holder", day)
            counts = F._rows(rows)
            snapshots[day] = {
                "filename": p.name,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "rows": len(rows), "distinct_raw_records": len(counts),
                "extra_raw_occurrences": sum(n - 1 for n in counts.values() if n > 1),
            }
        manifest = root / "evidence.json"
        manifest.write_text(json.dumps({
            "format": "qmt_002188_top10holder_exact_multiplicity_pin_v1",
            "symbol": D.CODE, "table": "Top10Holder",
            "allow_deduplication": False, "allow_apply": False,
            "allow_pending_clear": False, "human_approval_granted": False,
            "ledger_sha256": D.LEDGER_SHA,
            "historical_union_sha256": union_sha,
            "duplicate_row_sha256": sorted(duplicates),
            "selected_snapshots": snapshots,
            "capital_additive_review_scope": {
                "historical_report_keys": 108,
                "current_report_keys": 109,
                "exact_new_report_key": "20261119",
                "historical_capital_raw_versions": 110,
                "removed_report_keys": 0,
                "shared_economic_changed_keys": 0,
            },
        }), encoding="utf-8")

        class WorkerF(F):
            @staticmethod
            def _worker_batch(codes, mode, asof, lookback, directory,
                              timeout, progress):
                if codes != [D.CODE] or mode != "cache":
                    raise AssertionError("NOT_SINGLE_STOCK_CACHE_ONLY")
                if mutate_ledger_during_worker:
                    ledger.write_text(ledger.read_text() + " ", encoding="utf-8")
                result = {name: [] for name in E.FIN_TABLES}
                result["Capital"] = new_capital
                result["Top10Holder"] = cache_holders
                return {D.CODE: result}, []
        return ledger, manifest, snapshots, duplicates, union_sha, WorkerF

    def _call(self, *, missing_one_cache_repeat=False,
              mutate_ledger_during_worker=False,
              tamper_active_snapshot=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger, manifest, snaps, duplicates, union_sha, W = self._fixture(
                root, missing_one_cache_repeat=missing_one_cache_repeat,
                mutate_ledger_during_worker=mutate_ledger_during_worker)
            if tamper_active_snapshot:
                folder = root / "private" / "financial" / "Top10Holder" / D.CODE / "snapshots"
                selected_file = folder / snaps["2026-11-18"]["filename"]
                selected_file.write_bytes(selected_file.read_bytes() + b" ")
            original_sha = D.file_sha
            def safe_sha(path):
                if Path(path) == ledger:
                    if ledger.read_text().endswith(" "):
                        return "0" * 64
                    return D.LEDGER_SHA
                return original_sha(path)
            output = io.StringIO()
            with patch.object(P, "PINNED_002188_RAW_SHA256", duplicates), \
                 patch.object(P, "PINNED_002188_UNION_SHA256", union_sha), \
                 patch.object(P, "PINNED_002188_SNAPSHOTS", snaps), \
                 patch.object(D, "file_sha", side_effect=safe_sha), \
                 patch.object(D, "protect_clock"), \
                 redirect_stdout(output):
                if missing_one_cache_repeat:
                    with self.assertRaisesRegex(P.ReviewBlocked,
                                                "QMT_CACHE_MULTIPLICITY_CHANGED"):
                        D.run(root, manifest, E, W, P)
                    result = None
                elif mutate_ledger_during_worker:
                    with self.assertRaisesRegex(RuntimeError,
                                                "LEDGER_CHANGED_DURING_RUN"):
                        D.run(root, manifest, E, W, P)
                    result = None
                elif tamper_active_snapshot:
                    with self.assertRaisesRegex(RuntimeError,
                                                "SNAPSHOT_CONTENT_OR_SELECTION_CHANGED"):
                        D.run(root, manifest, E, W, P)
                    result = None
                else:
                    result = D.run(root, manifest, E, W, P)
            return result, output.getvalue()

    def test_pinned_779_plus_nine_one_stock_e2e_review_only(self):
        result, output = self._call()
        self.assertEqual(result["capital"]["old_report_keys"], 108)
        self.assertEqual(result["capital"]["current_report_keys"], 109)
        self.assertEqual(result["capital"]["added_report_keys"], ["20261119"])
        holder_proof = result["top10holder"]
        self.assertEqual(holder_proof["verified_repeated_raw_groups"], 9)
        self.assertEqual(holder_proof["historical_and_current_total_rows"], 788)
        self.assertTrue(holder_proof["history_and_cache_multiset_equal"])
        self.assertFalse(result["allow_deduplication"])
        self.assertFalse(result["allow_apply"])
        self.assertIn("PINNED_002188_REVIEW_COMPLETE_NO_COMMIT", output)
        self.assertLess(output.index("PINNED_002188_LEDGER_UNCHANGED_VERIFIED"),
                        output.index("PINNED_002188_REVIEW="))

    def test_pinned_cache_missing_one_repeat_never_completes(self):
        _, output = self._call(missing_one_cache_repeat=True)
        self.assertNotIn("PINNED_002188_REVIEW=", output)
        self.assertNotIn("PINNED_002188_REVIEW_COMPLETE", output)

    def test_pinned_ledger_mutation_never_publishes_review(self):
        _, output = self._call(mutate_ledger_during_worker=True)
        self.assertNotIn("PINNED_002188_REVIEW=", output)
        self.assertNotIn("PINNED_002188_REVIEW_COMPLETE", output)

    def test_pinned_snapshot_hash_drift_blocks_before_qmt(self):
        _, output = self._call(tamper_active_snapshot=True)
        self.assertNotIn("PINNED_002188_REVIEW=", output)
        self.assertNotIn("PINNED_002188_REVIEW_COMPLETE", output)



if __name__ == "__main__":
    unittest.main()
