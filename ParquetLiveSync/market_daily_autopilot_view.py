"""Shared read-only Daily Autopilot status presenter for both desktop GUIs.

This is a presentation adapter for the existing S1 shadow classifier.
It does not launch QMT, Windows Task Scheduler, retries or writes.
"""
from __future__ import annotations

from pathlib import Path

import market_daily_autopilot_shadow as SHADOW

LEVELS = {
    "ROUTINE_CONTINUATION": ("日常续扫正常", "ROUTINE"),
    "ATTENTION_REQUIRED": ("发现需处理的异常", "ACTION"),
    "EXECUTED_NEEDS_REVIEW": ("数据状态待核验", "REVIEW"),
    "EXECUTED_VERIFICATION_MISSING": ("缺少本轮校验证据", "REVIEW"),
}


def empty_view(reason: str = "") -> dict:
    note = "状态文件尚未齐备，无法判断运行健康度"
    if reason:
        note += "（" + str(reason)[:90] + "）"
    return {
        "level": "UNKNOWN",
        "run_day": "未确认",
        "headline": "最近任务：尚无可信的自动健康结果",
        "coverage": "财务覆盖：未确认 · 不自动认定已完成",
        "quality": "数据质量：未认证 · 跨源验证：未认证",
        "action": note,
        "valuation": "估值派生（总市值 / PE / PB）：尚未启用",
        "authority": "只读影子视图；正式20:05任务、游标和异常队列未修改",
    }


def presentation(report: dict) -> dict:
    if (not isinstance(report, dict)
            or report.get("status") != "DAILY_AUTOPILOT_SHADOW_REPORT_NO_EXECUTION"):
        raise ValueError("unsupported_daily_autopilot_shadow_evidence")
    state = report.get("execution_health")
    if state not in LEVELS:
        raise ValueError("unknown_autopilot_execution_health")
    name, level = LEVELS[state]
    coverage = report.get("coverage")
    quality = report.get("data_quality")
    if not isinstance(coverage, dict) or not isinstance(quality, dict):
        raise ValueError("missing_autopilot_health_dimensions")
    pending = coverage.get("pending_total")
    remaining = coverage.get("financial_remaining_unvisited")
    processed = coverage.get("financial_today_processed")
    if (type(pending) is not int or pending < 0
            or (remaining is not None and
                (type(remaining) is not int or remaining < 0))
            or (processed is not None and
                (type(processed) is not int or processed < 0))):
        raise ValueError("untrusted_autopilot_coverage")
    day = report.get("run_day")
    if not isinstance(day, str) or len(day) != 10:
        raise ValueError("missing_autopilot_run_day")
    def show(value):
        return str(value) if isinstance(value, int) and value >= 0 else "未确认"
    raw_status = report.get("receipt_execution_status", "UNVERIFIED")
    result = {
        "level": level,
        "run_day": day,
        "headline": "最近任务 " + day + "：" + name +
                    "（原始回执 " + str(raw_status) + "）",
        "coverage": ("财务本轮处理 " + show(processed) +
                     " 只 · 未遍历 " + show(remaining) +
                     " 只 · 待审 " + show(pending) + " 只"),
        "quality": ("数据质量：" +
                    str(quality.get("current_run_validation", "UNVERIFIED")) +
                    " · 跨源验证：" +
                    str(quality.get("cross_source_validation", "UNVERIFIED")) +
                    "（不等于全部认证）"),
        "valuation": "估值派生（总市值 / PE / PB）：尚未启用",
        "authority": "只读影子视图；正式20:05任务、游标和异常队列未修改",
    }
    if level == "ROUTINE":
        result["action"] = "暂无已证实的执行故障；按原计划继续，待审版本保留"
    elif level == "REVIEW":
        result["action"] = "校验证据不足或存在非计划内部分结果；请查看原始回执"
    else:
        failures = report.get("stage_execution_errors") or []
        qa = report.get("stage_quality_failures") or []
        reason = list(failures) + list(qa)
        result["action"] = ("需要查看故障诊断：" +
                            ("、".join(str(v) for v in reason[:3])
                             if reason else "质量或执行异常"))
    return result


def read_view(state_module: Path | str) -> dict:
    try:
        return presentation(SHADOW.inspect(Path(state_module)))
    except (SHADOW.HealthBlocked, OSError, ValueError, TypeError) as exc:
        return empty_view(type(exc).__name__)
