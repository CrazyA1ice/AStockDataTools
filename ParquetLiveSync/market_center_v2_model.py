"""V2.0 market-center *preview-only* data model. No QMT, download or writes.

Safe selections and latest private receipts are displayed, not executed.
A date/stock/model selection is not a capability certificate for updating
the physical all-market ledger or auditing historic PIT data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

CHINA = timezone(timedelta(hours=8))
MODULES = ("八周期行情", "板块", "除权", "财务")
MODES = ("更新数据", "数据核验")
MARKETS = ("SH", "SZ", "BJ")
SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
MAX_STOCKS = 500
MAX_SOURCE_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 2 * 1024 * 1024


class InvalidPlan(ValueError):
    pass


def safe_cutoff(now: datetime | None = None) -> date:
    """A candidate upper bound, NOT a certified actual trading calendar."""
    now = now or datetime.now(CHINA)
    if now.tzinfo is None or now.utcoffset() is None:
        raise InvalidPlan("必须使用带时区的北京时间")
    local = now.astimezone(CHINA)
    target = local.date()
    if (local.hour, local.minute) < (20, 5):
        target -= timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target


def clean_day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InvalidPlan("日期必须采用 YYYY-MM-DD")
    try:
        d = date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidPlan("日期不存在") from exc
    if d.isoformat() != value:
        raise InvalidPlan("日期格式不正确")
    return d


def parse_symbols(value: str) -> tuple[str, ...]:
    """Require explicit exchange suffix; never infer from six digits."""
    if not isinstance(value, str):
        raise InvalidPlan("股票列表必须是文本")
    parts = re.split(r"[,，;\s；]+", value.strip())
    found: dict[str, None] = {}
    for raw in parts:
        if not raw:
            continue
        token = raw.upper()
        if SYMBOL.fullmatch(token) is None:
            raise InvalidPlan("股票代码应为 000001.SZ 或 600519.SH 形式：" + raw[:32])
        found[token] = None
        if len(found) > MAX_STOCKS:
            raise InvalidPlan("单次预览最多 500 只股票")
    return tuple(found)


def plan_preview(*, mode: str, start: str, end: str, scope: str,
                 stock_text: str, modules, now: datetime | None = None) -> dict:
    """Validation is purely in-memory; no task launch or market file access."""
    if mode not in MODES:
        raise InvalidPlan("未知的操作模式")
    lo, hi = clean_day(start), clean_day(end)
    if lo > hi:
        raise InvalidPlan("开始日期不得晚于结束日期")
    ceiling = safe_cutoff(now)
    if hi > ceiling:
        raise InvalidPlan("日期超过北京时间 20:05 的当前安全候选上限：" + str(ceiling))
    if scope not in ("全部股票", "指定股票"):
        raise InvalidPlan("未知股票处理范围")
    stocks = parse_symbols(stock_text) if scope == "指定股票" else ()
    if scope == "指定股票" and not stocks:
        raise InvalidPlan("请至少选择一只股票")
    if not isinstance(modules, (list, tuple)):
        raise InvalidPlan("数据类型输入格式无效")
    normalized = tuple(dict.fromkeys(modules))
    if not normalized or any(item not in MODULES for item in normalized):
        raise InvalidPlan("至少选择一种支持展示的数据类型")
    return {
        "format": "market_center_v2_plan_preview_only_v1",
        "mode": mode,
        "start_date": lo.isoformat(),
        "end_date": hi.isoformat(),
        "scope": scope,
        "symbols": list(stocks),
        "symbol_count": len(stocks) if scope == "指定股票" else None,
        "data_types": list(normalized),
        "safe_candidate_cutoff": ceiling.isoformat(),
        "trading_calendar_confirmed": False,
        "stock_universe_membership_certified": False,
        "physical_data_certified": False,
        "allowed_to_execute": False,
        "existing_history_policy": "行情普通增量仅从最新已提交日后续传；已提交来源可幂等跳过，日期交叉重叠或版本冲突必须拒绝盲目覆盖；财务历史冲突继续隔离",
        "concurrent_task_policy": "实际更新必须经过同一执行锁；20:05计划任务运行中拒绝第二个写入作业，日志只读仍可查看",
        "existing_stock_day_coverage_scanned": False,
        "scheduled_task_live_state_checked": False,
        "reason": "V2-A 仅配置预览；指定日期/股票的更新与核验后端尚未验收，禁止隐式全市场执行",
    }


def _json_file(path: Path, cap: int) -> dict:
    """Read only a specific bounded JSON path. No directory walk."""
    if path.is_symlink() or not path.is_file():
        return {}
    if path.stat().st_size > cap:
        raise InvalidPlan("状态文件过大，拒绝读取：" + path.name)
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise InvalidPlan("状态文件无法解析：" + path.name) from exc
    if not isinstance(doc, dict):
        raise InvalidPlan("状态文件结构不是对象：" + path.name)
    return doc


def source_info(module_dir: Path) -> dict:
    """Display configured/possible sources, not observed successful crosschecks."""
    module_dir = Path(module_dir)
    override = module_dir / "work" / "market_update" / "sources.local.json"
    builtin = module_dir / "market_sources.json"
    used = override if override.is_file() and not override.is_symlink() else builtin
    doc = _json_file(used, MAX_SOURCE_BYTES)
    checks = doc.get("minute_cross_checks", {})
    if not isinstance(checks, dict):
        checks = {}
    names = {
        "eltdx": "eltdx：TDX 7709 分钟 OHLCVA 抽样",
        "tencent": "腾讯 m1：分钟 OHLC/时间抽样（不含金额）",
        "akshare": "akshare：近五日可选比对",
    }
    available = [human for key, human in names.items()
                 if isinstance(checks.get(key), dict)
                 and checks[key].get("enabled") is True]
    primary = doc.get("primary")
    if primary == "qmt":
        minute = "QMT / 已购分钟源（依既有校准门禁）"
    elif primary is None:
        minute = "数据源配置缺失：不能认定当前行情主来源"
    else:
        minute = "主来源配置为 " + str(primary)[:48] + "，尚未完成 V2 来源适配认证"
    official = doc.get("official_day_source")
    day = ("TDX 已接受 DAY 来源" if official == "TDX_accepted_daily_overlay"
           else "日线主来源未确认，请查阅当前实际更新日志")
    return {
        "config_file": "本地覆盖配置" if used == override else "项目默认配置",
        "market_minute_update": minute,
        "market_day_update": day,
        "market_week_month_update": "经认证的闭合派生及已购校准锚点",
        "other_update": "板块、除权、财务：QMT 对应服务或缓存",
        "minute_crosschecks_configured": available,
        "other_crosschecks": "板块、除权、财务尚无完整独立跨源认证",
        "source_config_loaded": bool(doc),
        "crosscheck_execution_evidenced": False,
        "source_selection_user_editable": False,
    }


def last_accepted_day(ledger: dict) -> str:
    try:
        months = ledger.get("periods", {}).get("1min", {})
    except AttributeError:
        return ""
    if not isinstance(months, dict):
        return ""
    days = []
    for value in months.values():
        if not isinstance(value, dict):
            continue
        for item in value.get("days", []):
            if isinstance(item, str):
                try:
                    if date.fromisoformat(item).isoformat() == item:
                        days.append(item)
                except ValueError:
                    continue
    return max(days, default="")


def latest_status(module_dir: Path, *, now: datetime | None = None) -> dict:
    """Read only the existing receipt and ledger; no implied run-to-run deltas."""
    module_dir = Path(module_dir)
    root = module_dir / "work"
    latest = _json_file(root / "last-afternoon-unified.json", MAX_RECEIPT_BYTES)
    ledger = _json_file(root / "market_update" / "commits.json", MAX_RECEIPT_BYTES)
    financial = _json_file(root / "qmt_extra" / "financial-cache-progress.json", MAX_RECEIPT_BYTES)
    pending = financial.get("pending")
    pending_count = len(pending) if isinstance(pending, dict) else None
    validation = latest.get("validation") or {}
    if not isinstance(validation, dict):
        validation = {}
    stages = latest.get("stage_records") or {}
    if not isinstance(stages, dict):
        stages = {}
    result = {
        "last_run_status": latest.get("status", "暂无记录"),
        "last_run_started": latest.get("china_start", "暂无记录"),
        "last_run_ended": latest.get("finished_local", "暂无记录"),
        "last_accepted_trading_day": last_accepted_day(ledger) or "未证明",
        "finance_pending_count": pending_count,
        "finance_pending_count_evidenced": pending_count is not None,
        "safe_candidate_cutoff": safe_cutoff(now).isoformat(),
        "qmt_last_preflight": latest.get("qmt_preflight_status", "暂无历史预检"),
        "qmt_is_live_now_verified": False,
        "execution_validation": validation.get("execution", "UNVERIFIED"),
        "data_validation": validation.get("data_validation", "UNVERIFIED"),
        "cross_validation": validation.get("cross_validation", "UNVERIFIED"),
        "stage_records": {
            stage: {
                "exit_code": (stages.get(stage) or {}).get("exit_code"),
                "log_path": (stages.get(stage) or {}).get("log_path", ""),
            } for stage in ("EIGHT_PERIODS", "SECTORS",
                            "ADJUSTMENTS_ROTATING", "FINANCIAL_DAILY")
        },
        "comparison": "暂无可靠的前后快照，无法计算本次净变化",
        "comparison_evidenced": False,
    }
    return result
