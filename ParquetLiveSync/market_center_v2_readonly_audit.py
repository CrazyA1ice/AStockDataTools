"""V2-B bounded local *read-only* Parquet stock/day evidence survey.

No QMT, downloads, Parquet writes, scheduler registration or guessed trading
days. Scans only explicit files/row groups selected by a bounded stock/date/
period scope and returns a non-certifying JSON observation.

For WEEK/MONTH, vendor timestamp labels are NOT trade-day completeness.
For any period, NO_ROWS_OBSERVED cannot prove an expected listed stock/day:
halt/suspension/IPO/holidays and the source's coverage are not inferred.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import re
import time
from typing import Any

from market_center_v2_minute_grid import (
    PERIOD_MINUTES, GridScopeError, inspect_minute_labels,
)

PERIODS = ("1min", "5min", "15min", "30min", "60min", "day", "week", "month")
MINUTE_COUNTS = {"1min": 240, "5min": 48, "15min": 16, "30min": 8, "60min": 4}
CN = timezone(timedelta(hours=8))
FROZEN_ASOF = date(2026, 11, 19)
MAX_STOCKS = 20
MAX_DAYS = 31
MAX_FILES = 32
MAX_SELECTED_ROWGROUPS = 160
MAX_DECOMPRESSED_ROWS = 2_500_000
MAX_GROUP_ROWS = 256_000
REQUIRED = ("ts", "symbol", "open", "high", "low", "close", "volume", "amount")
CODE_RE = re.compile(r"([0-9]{6})\.(SH|SZ|BJ)\Z", re.I)
PHYSICAL_RE = re.compile(r"(SH|SZ|BJ)([0-9]{6})\Z", re.I)
SUFFIX_RE = re.compile(r"([0-9]{6})[.:-](SH|SZ|BJ|XSHG|XSHE|BSE)\Z", re.I)
EXCHANGES = {"XSHG": "SH", "XSHE": "SZ", "BSE": "BJ"}


class AuditBlocked(ValueError):
    """Fail-closed audit gate. No output may be presented as certified."""


def _check_deadline(deadline_monotonic: float | None):
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise AuditBlocked("audit_wall_clock_budget_exceeded")


def _day(value: str) -> date:
    if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise AuditBlocked("date_format_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AuditBlocked("date_value_invalid") from exc
    if parsed.isoformat() != value:
        raise AuditBlocked("date_format_invalid")
    return parsed


def _validate_scope(start: str, end: str, symbols: list[str] | tuple[str, ...],
                    periods: list[str] | tuple[str, ...]):
    lo, hi = _day(start), _day(end)
    if hi < lo or (hi - lo).days + 1 > MAX_DAYS or hi > FROZEN_ASOF:
        raise AuditBlocked("date_scope_invalid_or_exceeds_frozen_asof")
    if type(symbols) not in (list, tuple) or not 1 <= len(symbols) <= MAX_STOCKS:
        raise AuditBlocked("explicit_1_to_20_stocks_required")
    codes = []
    for sym in symbols:
        if type(sym) is not str or CODE_RE.fullmatch(sym) is None:
            raise AuditBlocked("explicit_exchange_symbol_required")
        code, exchange = CODE_RE.fullmatch(sym).groups()
        codes.append((exchange.upper() + code, code + "." + exchange.upper()))
    if len(set(codes)) != len(codes):
        raise AuditBlocked("duplicate_selected_stock_refused")
    if type(periods) not in (list, tuple) or not 1 <= len(periods) <= len(PERIODS):
        raise AuditBlocked("explicit_periods_required")
    if len(set(periods)) != len(periods) or any(p not in PERIODS for p in periods):
        raise AuditBlocked("unknown_or_duplicate_period")
    return lo, hi, codes


def _physical_symbol(value: Any) -> str | None:
    if type(value) is not str:
        return None
    v = value.upper()
    pref = PHYSICAL_RE.fullmatch(v)
    if pref:
        return pref.group(1) + pref.group(2)
    suffix = SUFFIX_RE.fullmatch(v)
    if suffix:
        code, market = suffix.groups()
        return EXCHANGES.get(market, market) + code
    return None


def _stat(path: Path):
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


def _safe_root(path: str | Path) -> Path:
    root = Path(path)
    if (not root.is_absolute() or root.name.lower() != "allcycleastockdata"
            or not root.is_dir()
            or any(part.is_symlink() for part in (root, *root.parents))):
        raise AuditBlocked("explicit_unlinked_market_root_required")
    return root


def _filenames(root: Path, period: str, lo: date, hi: date) -> list[tuple[str, Path | None]]:
    directory = root / period
    if not directory.is_dir() or directory.is_symlink():
        raise AuditBlocked("invalid_period_directory_" + period)
    months = []
    y, m = lo.year, lo.month
    while (y, m) <= (hi.year, hi.month):
        annual = directory / (str(y) + ".parquet")
        monthly = directory / (f"{y}-{m:02d}.parquet")
        if annual.is_symlink() or monthly.is_symlink():
            raise AuditBlocked("symlink_partition_refused_" + period)
        if annual.exists() and monthly.exists():
            raise AuditBlocked("annual_monthly_partition_collision_" + period)
        selected = monthly if monthly.is_file() else annual if annual.is_file() else None
        if selected is not None and (selected.is_symlink() or selected.stat().st_size == 0):
            raise AuditBlocked("invalid_parquet_source_" + period)
        months.append((f"{y}-{m:02d}", selected))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


def _schema(schema) -> bool:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise AuditBlocked("pyarrow_required") from exc
    expected = {"ts": pa.int64(), "symbol": pa.string()}
    expected.update({n: pa.float64() for n in REQUIRED[2:]})
    return (len(schema.names) == len(set(schema.names))
            and all(name in schema.names and schema.field(name).type == typ
                    for name, typ in expected.items()))


def survey(*, root: str | Path, start: str, end: str,
           symbols: list[str] | tuple[str, ...],
           periods: list[str] | tuple[str, ...],
           explicit_readonly: bool = False,
           deadline_monotonic: float | None = None) -> dict:
    """Bounded one-shot audit; rejects over-budget reads BEFORE row decompression."""
    if explicit_readonly is not True:
        raise AuditBlocked("explicit_readonly_optin_required")
    _check_deadline(deadline_monotonic)
    lo, hi, pairs = _validate_scope(start, end, symbols, periods)
    selected = {canonical for canonical, _ in pairs}
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise AuditBlocked("pyarrow_required") from exc
    parent = _safe_root(root)
    files: dict[str, list[tuple[str, Path | None]]] = {
        period: _filenames(parent, period, lo, hi) for period in periods
    }
    if sum(len(v) for v in files.values()) > MAX_FILES:
        raise AuditBlocked("file_selection_budget_exceeded")

    low_ms = int(datetime.combine(lo, datetime.min.time(), tzinfo=CN).timestamp() * 1000)
    exclusive_ms = int(datetime.combine(hi + timedelta(days=1),
                                         datetime.min.time(), tzinfo=CN).timestamp() * 1000)
    queue: list[tuple[str, str, Path, tuple[int, int], list[int]]] = []
    missing: list[dict] = []
    candidate_rows = 0
    candidate_groups = 0
    visited_files: set[tuple[str, Path]] = set()
    # Phase 1: inspect footers only; reject expensive scope before data access.
    for period, partitions in files.items():
        for partition, path in partitions:
            _check_deadline(deadline_monotonic)
            if path is None:
                missing.append({"period": period, "partition": partition,
                                "reason": "PHYSICAL_PARTITION_NOT_FOUND"})
                continue
            if (period, path) in visited_files:
                # Multiple requested months can share one historical annual
                # Parquet. Decode it only once; do not double-count keys.
                continue
            visited_files.add((period, path))
            prior = _stat(path)
            try:
                reader = pq.ParquetFile(str(path))
                try:
                    if not _schema(reader.schema_arrow):
                        raise AuditBlocked("canonical_eight_column_schema_required")
                    meta = reader.metadata
                    index = reader.schema_arrow.get_field_index("ts")
                    ids = []
                    for i in range(meta.num_row_groups):
                        _check_deadline(deadline_monotonic)
                        group = meta.row_group(i)
                        col = group.column(index)
                        stats = col.statistics
                        if stats and stats.has_min_max:
                            minimum, maximum = stats.min, stats.max
                            if (type(minimum) is not int or type(maximum) is not int
                                    or minimum > maximum):
                                raise AuditBlocked("invalid_timestamp_statistics")
                            if minimum >= exclusive_ms or maximum < low_ms:
                                continue
                        if group.num_rows > MAX_GROUP_ROWS:
                            raise AuditBlocked("single_row_group_budget_exceeded")
                        ids.append(i)
                        candidate_groups += 1
                        candidate_rows += group.num_rows
                        if (candidate_groups > MAX_SELECTED_ROWGROUPS
                                or candidate_rows > MAX_DECOMPRESSED_ROWS):
                            raise AuditBlocked("candidate_row_group_budget_exceeded_reduce_scope")
                finally:
                    reader.close()
            except AuditBlocked:
                raise
            except Exception as exc:
                raise AuditBlocked("parquet_metadata_unreadable_" + period) from exc
            if _stat(path) != prior:
                raise AuditBlocked("market_file_changed_during_metadata_scan")
            queue.append((period, partition, path, prior, ids))

    seen: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    problems: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int))
    inspected_rows = 0
    for period, _partition, path, prior, rowgroups in queue:
        _check_deadline(deadline_monotonic)
        if _stat(path) != prior:
            raise AuditBlocked("market_file_changed_before_read")
        try:
            reader = pq.ParquetFile(str(path))
            try:
                for idx in rowgroups:
                    _check_deadline(deadline_monotonic)
                    for batch in reader.iter_batches(
                            row_groups=[idx], batch_size=8192,
                            columns=list(REQUIRED), use_threads=False):
                        _check_deadline(deadline_monotonic)
                        values = batch.to_pydict()
                        inspected_rows += batch.num_rows
                        if inspected_rows > MAX_DECOMPRESSED_ROWS:
                            raise AuditBlocked("runtime_read_budget_exceeded")
                        for pos in range(batch.num_rows):
                            canonical = _physical_symbol(values["symbol"][pos])
                            if canonical not in selected:
                                continue
                            stamp = values["ts"][pos]
                            if type(stamp) is not int:
                                raise AuditBlocked("selected_stock_timestamp_invalid")
                            if not low_ms <= stamp < exclusive_ms:
                                continue
                            try:
                                day = datetime.fromtimestamp(stamp / 1000, CN).date().isoformat()
                            except (ValueError, OSError, OverflowError) as exc:
                                raise AuditBlocked("timestamp_outside_supported_range") from exc
                            key = (period, canonical, day)
                            counts[key] += 1
                            if stamp in seen[key]:
                                problems[key]["DUPLICATE_SYMBOL_TIMESTAMP"] += 1
                            else:
                                seen[key].add(stamp)
                            bars = [values[name][pos] for name in REQUIRED[2:]]
                            if any(type(v) not in (float, int) or not math.isfinite(v)
                                   for v in bars):
                                problems[key]["NONFINITE_OHLCVA"] += 1
                            else:
                                op, high, low, close, volume, amount = bars
                                if high < max(op, close, low) or low > min(op, close):
                                    problems[key]["OHLC_INVALID"] += 1
                                if volume < 0 or amount < 0:
                                    problems[key]["NEGATIVE_VOLUME_AMOUNT"] += 1
            finally:
                reader.close()
        except AuditBlocked:
            raise
        except Exception as exc:
            raise AuditBlocked("parquet_selected_rows_unreadable_" + period) from exc
        if _stat(path) != prior:
            raise AuditBlocked("market_file_changed_during_read")

    _check_deadline(deadline_monotonic)
    days = [(lo + timedelta(days=d)).isoformat()
            for d in range((hi - lo).days + 1)]
    observations = []
    minute_grid_observations = []
    for period in periods:
        for canonical, presentation in pairs:
            for day in days:
                key = (period, canonical, day)
                count = counts[key]
                errors = dict(problems.get(key, {}))
                # Counts on a selected label day are evidence, not a full
                # trade-calendar or 1m grid proof; vendor timestamps vary.
                # Do NOT mark 239 versus a 240-bar reference as a physical
                # corruption. Vendor timestamp contract, suspensions and
                # calendar are not certified by this baseline count.
                count_gap_candidate = (
                    abs(count - MINUTE_COUNTS[period])
                    if count and period in MINUTE_COUNTS
                    else None)
                if period in PERIOD_MINUTES:
                    try:
                        minute = inspect_minute_labels(
                            period=period, day=day,
                            timestamps_ms=seen[key])
                    except GridScopeError as exc:
                        raise AuditBlocked(
                            "minute_label_grid_observation_blocked_" + str(exc)) from exc
                    minute_grid_observations.append({
                        "symbol": presentation, **minute,
                    })
                observations.append({
                    "period": period,
                    "symbol": presentation,
                    "timestamp_label_day": day,
                    "rows": count,
                    "standard_bar_count_difference_candidate": count_gap_candidate,
                    "status": ("NO_ROWS_OBSERVED" if count == 0 else
                               "ANOMALY_OBSERVED" if errors else
                               "ROWS_OBSERVED_UNCERTIFIED"),
                    "anomalies": errors,
                })
    return {
        "status": "V2B_BOUNDED_READONLY_OBSERVATION_NOT_CERTIFIED",
        "scope": {"start": start, "end": end,
                  "periods": list(periods),
                  "stocks": [p for _, p in pairs]},
        "source_partitions": [
            {"period": period, "file_name": path.name,
             "bytes_before": prior[0], "mtime_ns_before": prior[1],
             "row_groups_decompressed": len(ids)}
            for period, _, path, prior, ids in queue
        ],
        "missing_partitions": missing,
        "row_group_budget": {"rows_preflight": candidate_rows,
                             "groups_preflight": candidate_groups,
                             "rows_inspected": inspected_rows},
        "observations": observations,
        "minute_grid_observations": minute_grid_observations,
        "minute_grid_is_comparison_only": True,
        "exchange_trading_calendar_verified": False,
        "no_rows_does_not_certify_missing_trading_day": True,
        "week_month_timestamp_not_exact_trading_day": True,
        "official_source_reacquired": False,
        "source_crosscheck_completed": False,
        "physical_snapshot_immutability_certified": False,
        "finance_pit_certified": False,
        "adjusted_return_certified": False,
        "allowed_market_write": False,
        "database_writes": False,
        "market_file_writes": False,
        "qmt_calls": 0,
    }
