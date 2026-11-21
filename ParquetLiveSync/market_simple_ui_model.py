"""Pure and bounded presentation/plan model for the simplified market UI.

No source download, market write, schedule edit or calendar-day guessing.
"""
from __future__ import annotations

from datetime import date
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
