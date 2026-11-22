"""Pure and bounded presentation/plan model for the simplified market UI.

No source download, market write, schedule edit or calendar-day guessing.
"""
from __future__ import annotations

from datetime import date
from collections import Counter
from pathlib import Path
import re

from market_center_v2_model import parse_symbols
from market_update_dashboard import accepted_minute_day, safe_refresh_limit

PERIODS = (
    ("1min", "1分钟"), ("5min", "5分钟"),
    ("15min", "15分钟"), ("30min", "30分钟"),
    ("60min", "60分钟"), ("day", "日线"),
    ("week", "周线"), ("month", "月线"),
)
EXTRAS = (
    ("SECTORS", "板块"),
    ("ADJUSTMENTS_ROTATING", "除权"),
    ("FINANCIAL_DAILY", "财务"),
)
MODULES = ("八周期行情", "板块", "除权", "财务")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class InvalidSimplePlan(ValueError):
    pass


def _iso(text: str) -> str:
    if not isinstance(text, str) or DATE.fullmatch(text) is None:
        raise InvalidSimplePlan("日期需要使用YYYY-MM-DD")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise InvalidSimplePlan("不存在的日期") from exc


def _known_days(ledger: dict, key: str) -> tuple[str, ...]:
    if not isinstance(ledger, dict):
        return ()
    raw = (ledger.get("periods") or {})
    if not isinstance(raw, dict):
        return ()
    months = raw.get(key)
    if not isinstance(months, dict):
        return ()
    found = set()
    for month, meta in months.items():
        if (not isinstance(month, str) or not isinstance(meta, dict)
                or not isinstance(meta.get("days"), list)):
            continue
        for item in meta["days"]:
            try:
                day = _iso(item)
            except InvalidSimplePlan:
                continue
            if day[:7] == month:
                found.add(day)
    return tuple(sorted(found))


def initial_date(ledger: dict, *, cutoff: date | None = None) -> tuple[str, str]:
    """Fallback from last locally COMMITTED trading session, not a holiday guess.

    A returned date is NOT proof that the exchange's latest session was
    ingested. The QMT calendar is queried separately by the desktop GUI.
    """
    limit = cutoff or safe_refresh_limit()
    if not isinstance(limit, date):
        raise ValueError("invalid_date_cutoff")
    candidate = accepted_minute_day(ledger)
    try:
        known = _iso(candidate)
    except InvalidSimplePlan:
        return "", "未取得已提交交易日；等待QMT日历"
    if date.fromisoformat(known) > limit:
        return "", "已提交日期超过本轮安全截止，拒绝自动选择"
    return known, "本地已提交交易日（可能滞后）"


def coverage_rows(ledger: dict, receipt: dict, progress: dict) -> list[dict]:
    if not isinstance(ledger, dict):
        ledger = {}
    if not isinstance(receipt, dict):
        receipt = {}
    if not isinstance(progress, dict):
        progress = {}
    val = receipt.get("validation")
    sections = val.get("sections") if isinstance(val, dict) else {}
    if not isinstance(sections, dict):
        sections = {}
    result = []
    for key, label in PERIODS:
        days = _known_days(ledger, key)
        result.append({
            "key": key, "name": label,
            "begin": days[0] if days else "未核实",
            "end": days[-1] if days else "未核实",
            "count": len(days),
            "updated": "未单独记录",
            # A four-stage PASS does not prove eight independent
            # time-series source comparisons or missing-day closure.
            "multi_source": "未核验",
            "detail": ("已记录%d个交易日期；中间缺口未独立认证" % len(days)
                       if days else "尚无可用的本地已提交日期索引"),
        })
    for stage, label in EXTRAS:
        item = sections.get(stage)
        item = item if isinstance(item, dict) else {}
        cross = str(item.get("cross_validation", "UNVERIFIED")).upper()
        quality = str(item.get("data_validation", "UNVERIFIED")).upper()
        if cross == "PASS":
            cross_label = "已通过"
        elif cross == "FAIL":
            cross_label = "失败"
        else:
            cross_label = "未核验"
        if quality == "FAIL":
            cross_label = "失败"
        if stage == "FINANCIAL_DAILY":
            updated = progress.get("daily_date", "未核实")
            scope = "待审%d只；未访问股票数以本轮校验回执为准" % len(
                progress.get("pending", {})) if isinstance(progress.get("pending"), dict) else "待审数量未核实"
        else:
            updated = "未单独记录"
            scope = "来源明细及起止日期尚无独立认证"
        result.append({
            "key": stage, "name": label,
            "begin": "未核实", "end": "未核实",
            "count": None, "updated": updated,
            "multi_source": cross_label,
            "detail": ("%s；数据校验%s；跨源%s；%s" %
                       (str(item.get("detail", "无本次详情"))[:180],
                        quality, cross, scope)),
        })
    return result


def preview_request(*, mode: str, scope: str, stocks: str,
                    start: str, end: str, modules: list[str],
                    cutoff: date | None = None) -> dict:
    if mode not in ("增量更新", "重新下载并比对"):
        raise InvalidSimplePlan("选择更新方式")
    if scope not in ("全市场", "自选股票"):
        raise InvalidSimplePlan("选择股票范围")
    a, b = _iso(start), _iso(end)
    if a > b:
        raise InvalidSimplePlan("开始日期晚于结束日期")
    if date.fromisoformat(b) > (cutoff or safe_refresh_limit()):
        raise InvalidSimplePlan("结束日期超过当前允许的盘后截止")
    if not isinstance(modules, list) or not modules or any(
            m not in MODULES for m in modules):
        raise InvalidSimplePlan("至少选择一种有效数据类型")
    symbols = parse_symbols(stocks) if scope == "自选股票" else ()
    if scope == "自选股票" and not symbols:
        raise InvalidSimplePlan("请填写有效股票代码")
    return {
        "status": "SELECTION_PREVIEW_ONLY",
        "mode": mode, "scope": scope, "symbols": list(symbols),
        "start": a, "end": b, "modules": list(dict.fromkeys(modules)),
        "allowed_to_execute_selected_range": False,
        "legacy_all_market_resume_is_separate": True,
        "existing_versions_preserved": True,
    }


def finance_cache_refresh_scope(plan: dict) -> dict:
    """Authorize only the bounded QMT vendor-cache operation, never import.

    The actual Windows runner independently rechecks these limits and takes
    the same named mutex as the production 20:05 runner.
    """
    if (not isinstance(plan, dict)
            or plan.get("status") != "SELECTION_PREVIEW_ONLY"
            or plan.get("mode") != "增量更新"
            or plan.get("scope") != "自选股票"
            or plan.get("modules") != ["财务"]):
        raise InvalidSimplePlan("仅支持自选股票的财务增量缓存刷新")
    codes = plan.get("symbols")
    if (not isinstance(codes, list) or
            not 1 <= len(codes) <= 5 or
            any(not isinstance(s, str) for s in codes) or
            codes != list(dict.fromkeys(codes))):
        raise InvalidSimplePlan("财务缓存每次仅支持1至5只不同股票")
    normalized = parse_symbols(",".join(codes))
    if tuple(codes) != normalized:
        raise InvalidSimplePlan("股票代码及交易所标识必须规范一致")
    start, end = _iso(plan.get("start")), _iso(plan.get("end"))
    if start > end or (date.fromisoformat(end) -
                       date.fromisoformat(start)).days > 30:
        raise InvalidSimplePlan("财务缓存公告日期区间不能超过31天")
    return {
        "status": "QMT_CACHE_REFRESH_SCOPE_VALIDATED_NOT_EXECUTED",
        "symbols": list(codes),
        "start": start, "end": end,
        "qmt_vendor_cache_can_change_after_explicit_user_confirmation": True,
        "official_finance_parquet_not_modified": True,
        "official_finance_progress_not_modified": True,
        "financial_history_conflicts_not_auto_approved": True,
    }


def finance_pending_brief(progress: dict) -> str:
    """Tiny refresh-safe summary from the ledger already read by the GUI."""
    if not isinstance(progress, dict) or not isinstance(progress.get("pending"), dict):
        return "财务待审：账本不可用，不能推断为零；可在异常与日志页检查。"
    pending = progress["pending"]
    counts = Counter()
    for item in pending.values():
        if not isinstance(item, dict) or not isinstance(item.get("reason"), str):
            return "财务待审：记录格式待核实；不要继续正式财务入库。"
        counts[item["reason"]] += 1
    if not pending:
        return "财务待审：账本内暂无待审记录（不代表财务历史已跨源核验）。"
    known = {"SOURCE_HISTORY_CONFLICT", "CACHE_DECODE_ERROR", "NO_CACHE"}
    extra = sum(n for reason, n in counts.items() if reason not in known)
    return (
        "财务待审 %d 只：历史差异 %d、缓存解码 %d、无缓存 %d、其他 %d。"
        "可点“检查财务问题（只读）”查看原因；不会覆盖旧历史。"
        % (len(pending), counts["SOURCE_HISTORY_CONFLICT"],
           counts["CACHE_DECODE_ERROR"], counts["NO_CACHE"], extra)
    )


def finance_root_from_progress(progress: dict) -> Path:
    """Derive the stock root; never guess D:\\stock or auto-create folders."""
    if not isinstance(progress, dict) or not isinstance(progress.get("root"), str):
        raise InvalidSimplePlan("正式财务账本未提供数据根目录")
    extra = Path(progress["root"])
    if (not extra.is_absolute() or extra.name.lower() != "qmt_extra"
            or extra.parent.name.lower() != "allcycleastockdata"):
        raise InvalidSimplePlan("账本的数据根目录格式不符合预期，已拒绝检查")
    return extra.parent.parent


def finance_issue_report_view(report: dict) -> str:
    """Plain Chinese operator guidance, never a repair or commit approval."""
    if (not isinstance(report, dict)
            or report.get("status") !=
               "S9_FULL_PENDING_METADATA_CENSUS_READONLY_NOT_SOURCE_CERTIFIED"
            or report.get("can_commit") is not False
            or report.get("can_apply") is not False
            or report.get("all_historical_versions_verified") is not False
            or report.get("qmt_calls") != 0):
        raise InvalidSimplePlan("财务诊断回执身份不匹配，不能展示为安全结果")
    total = report.get("ledger_pending_total")
    reasons = report.get("pending_by_reason")
    first = report.get("first_recorded_conflict_table_counts")
    missing = report.get("per_share_without_local_snapshots")
    rows = report.get("rows_on_page")
    if (type(total) is not int or total < 0
            or not isinstance(reasons, dict)
            or any(type(v) is not int or v < 0 for v in reasons.values())
            or sum(reasons.values()) != total
            or not isinstance(first, dict)
            or any(type(v) is not int or v < 0 for v in first.values())
            or type(missing) is not int or not 0 <= missing <= total
            or not isinstance(rows, list) or len(rows) > 20):
        raise InvalidSimplePlan("财务诊断计数或明细格式异常")
    kinds = ("Capital", "Top10Holder", "Top10FlowHolder",
             "HolderNum", "UNCLASSIFIED")
    pieces = [
        "已核对账本待审 %d 只（仅本地目录元数据，未连接QMT来源）。" % total,
        "历史差异 %d；缓存解码 %d；无缓存 %d。" % (
            reasons.get("SOURCE_HISTORY_CONFLICT", 0),
            reasons.get("CACHE_DECODE_ERROR", 0),
            reasons.get("NO_CACHE", 0)),
        "已记录的首个历史冲突表：" +
        ("，".join("%s %d" % (name, first[name])
                  for name in kinds if first.get(name)) or "暂无") +
        "（不是全部差异表）。",
        "PerShare 无本地快照 %d/%d；不能据此判断QMT来源为空。" %
        (missing, total),
    ]
    states = report.get("nine_table_local_state_counts", [])
    if not isinstance(states, list):
        raise InvalidSimplePlan("九表快照状态计数格式异常")
    state_totals = Counter()
    for item in states:
        if (not isinstance(item, dict)
                or item.get("state") not in ("M", "U", "R", "P", "A")
                or type(item.get("count")) is not int
                or item["count"] < 0):
            raise InvalidSimplePlan("九表快照状态计数格式异常")
        state_totals[item["state"]] += item["count"]
    if sum(state_totals.values()) != total * 9:
        raise InvalidSimplePlan("九表快照状态总数与待审股票不一致")
    pieces.append(
        "九表本地状态（股票×表）：无快照%d、未pin%d、部分固定%d、"
        "元数据已固定%d、同日版本歧义%d；不代表内容已经认证。" %
        (state_totals["M"], state_totals["U"], state_totals["R"],
         state_totals["P"], state_totals["A"]))
    decode = report.get("cache_decode_error_stocks", [])
    if not isinstance(decode, list) or any(not isinstance(x, str) for x in decode):
        raise InvalidSimplePlan("缓存解码明细格式异常")
    if decode:
        pieces.append("缓存解码待查股票：" + "、".join(decode[:8]) + "。")
    problems = report.get("journal_counts", {})
    if not isinstance(problems, dict) or any(
            type(v) is not int or v < 0 for v in problems.values()):
        raise InvalidSimplePlan("事务日志计数格式异常")
    pieces.append("既有事务日志：%d 条；有记录需单独核对，不能自动重放。" %
                  sum(problems.values()))
    for row in rows[:3]:
        if not isinstance(row, dict) or not isinstance(row.get("nine_table_states"), dict):
            raise InvalidSimplePlan("财务诊断股票明细格式异常")
        code = str(row.get("symbol", "?"))
        category = str(row.get("reason", "?"))
        table = row.get("first_recorded_conflict_table") or "未明确"
        states = row["nine_table_states"]
        missing_tables = [name for name, value in states.items() if value == "M"]
        unpinned_tables = [name for name, value in states.items()
                           if value in ("U", "R", "A")]
        pieces.append(
            "%s：%s；首阻断表%s；无快照[%s]；待固定版本[%s]。" %
            (code, category, table, "、".join(missing_tables) or "无",
             "、".join(unpinned_tables) or "无"))
    pieces.append(
        "建议：单股解码错误可在“下载 / 更新”页选自选股票、财务、"
        "增量更新，限定公告日期后明确确认刷新QMT本地缓存；"
        "如仍失败须检查QMT接口。历史差异需保留旧版本、先核对来源，"
        "本诊断不会补pin、清理待审记录或提交财务Parquet。"
    )
    return "\n".join(pieces)
