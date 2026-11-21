"""Conservative, pure read-only advice for V2G2 market-audit observations.

A physical Parquet observation is NOT a certified exchange trading-day,
stock eligibility, verified source, or permission to backfill/overwrite.

In particular, do not treat finance-daily task errors in the same-run
receipt as explanations of historical market bar anomalies.
"""
from __future__ import annotations

from collections import Counter

MARKET_INTERPRETATIONS = {
    "RECORDS_PRESENT_NOT_CERTIFIED": (
        "发现物理记录，完整性未认证",
        "可查看原始记录及对应日期；有记录不代表当日全部行情齐全。",
        "如需确认完整性，需要官方交易日历、有效股票池和独立行情参照。",
    ),
    "PHYSICAL_ANOMALY_NEEDS_REVIEW": (
        "行情物理异常待复核",
        "先检查该股票、周期、日期的异常字段及原始行组证据。",
        "需核对时间标签、行情口径、权威来源和源文件版本；禁止直接覆盖。",
    ),
    "PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED": (
        "物理记录与来源声明存在矛盾",
        "对照原始记录与本地声明的交易日/停牌/上市状态。",
        "本地声明的文件SHA仅保证文件完整性，不能证明来源真实；禁止自动删除。",
    ),
    "NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN": (
        "未观察到记录，交易资格未知",
        "先确认交易日、是否上市及当日是否停牌；未观察到不等于缺失。",
        "获得经过核实的交易日历和上市/停牌状态后，再判断是否需要重新核验。",
    ),
    "NO_ROWS_NONTRADING_DECLARED_UNCERTIFIED": (
        "声明非交易日，未独立认证",
        "查看声明所依据的交易日历和对应市场。",
        "未经独立认证，不将该声明认定为真实，也不自动补缺。",
    ),
    "NO_ROWS_PRELISTING_DECLARED_UNCERTIFIED": (
        "声明上市前，未独立认证",
        "复核股票正式上市日期及相应交易市场。",
        "来源真实性未确认，不能据此判定应当无记录。",
    ),
    "NO_ROWS_POSTLISTING_DECLARED_UNCERTIFIED": (
        "声明上市资格结束，未独立认证",
        "检查退市、终止上市等有效日期记录。",
        "需要独立来源验证，不自动清理旧数据。",
    ),
    "NO_ROWS_SUSPENDED_DECLARED_UNCERTIFIED": (
        "声明停牌，未独立认证",
        "复核停牌公告、对应日期以及行情源的停牌记录口径。",
        "停牌声明未经认证，不自动补写零成交或删除其他记录。",
    ),
    "NO_ROWS_ELIGIBILITY_INDETERMINATE": (
        "缺失与交易资格均无法确定",
        "需要先确认交易日历、股票资格与数据分区完整性。",
        "证据不足，既不判定缺失，也不允许自动回填。",
    ),
    "PHYSICAL_PARTITION_MISSING_STOCK_GAP_UNDETERMINED": (
        "物理数据分区不存在",
        "先核对该周期的月份分区、路径及实际文件清单。",
        "分区缺失不等于其中每只股票都缺失；核实源文件和日期范围后再复核。",
    ),
    "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED": (
        "疑似行情缺失，数据源未认证",
        "逐项复核交易日、上市/停牌状态以及独立可靠行情参照。",
        "这只是候选缺失，已确认缺失数仍为0；不能直接下载或回补。",
    ),
    "LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF": (
        "周/月周期需要区间闭合证明",
        "核对本周期起止范围、实际最后交易日以及时间戳标签规则。",
        "周/月时间戳标签不能直接当作当天应有行情的证明。",
    ),
}
CANDIDATES = frozenset({
    "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED",
    "PHYSICAL_PARTITION_MISSING_STOCK_GAP_UNDETERMINED",
})
ALERTS = frozenset({
    "PHYSICAL_ANOMALY_NEEDS_REVIEW",
    "PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED",
})


class AuditFlowBlocked(ValueError):
    """No supported result/selection, or evidence does not permit guidance."""


def _row(row: object) -> dict:
    if type(row) is not dict:
        raise AuditFlowBlocked("invalid_audit_observation")
    interpretation = row.get("interpretation")
    if (type(interpretation) is not str
            or interpretation not in MARKET_INTERPRETATIONS):
        raise AuditFlowBlocked("unknown_interpretation_refuse_repair_advice")
    if (type(row.get("symbol")) is not str
            or type(row.get("period")) is not str
            or type(row.get("label_day")) is not str
            or type(row.get("rows")) is not int or row["rows"] < 0):
        raise AuditFlowBlocked("incomplete_audit_observation")
    return row


def explain_observation(row: dict) -> dict:
    """Explain a selected read-only row; NEVER approve a repair."""
    record = _row(row)
    code = record["interpretation"]
    headline, first, prerequisite = MARKET_INTERPRETATIONS[code]
    return {
        "status": "V2G2_OBSERVATION_REVIEW_NOT_CERTIFIED",
        "title": headline,
        "focus": (record["symbol"] + " / " + record["period"] +
                  " / " + record["label_day"]),
        "next_step": first,
        "required_evidence": prerequisite,
        "interpretation": code,
        "confirmed_missing_count": 0,
        "can_download": False,
        "can_repair": False,
        "market_file_writes": False,
        "finance_fault_link_certified": False,
    }


def summarize_readonly_report(report: dict) -> dict:
    """Only consume the UI's bounded in-memory JSON audit report.

    The UI report is derived from V2-B physical observations plus V2-B2
    evidence gate. Reject arbitrary reports that falsely claim write access.
    """
    if type(report) is not dict or report.get("market_file_writes") is not False:
        raise AuditFlowBlocked("read_only_audit_report_required")
    if report.get("qmt_calls") != 0:
        raise AuditFlowBlocked("market_audit_qmt_call_claim")
    evidence = report.get("evidence_interpretation")
    scope = report.get("scope")
    if (type(evidence) is not dict
            or evidence.get("status") != "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED"
            or evidence.get("allowed_repair_or_backfill") is not False
            or evidence.get("source_authenticity_certified") is not False
            or evidence.get("confirmed_missing_count") != 0
            or type(scope) is not dict
            or type(evidence.get("observations")) is not list):
        raise AuditFlowBlocked("unverified_evidence_gate_report")
    rows = evidence["observations"]
    counter = Counter()
    for item in rows:
        code = _row(item)["interpretation"]
        counter[code] += 1
    alert_count = sum(counter[key] for key in ALERTS)
    candidate_count = sum(counter[key] for key in CANDIDATES)
    unknown_count = sum(value for key, value in counter.items()
                        if key.startswith("NO_ROWS") or
                        key == "LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF")
    if alert_count:
        title = "发现" + str(alert_count) + "条行情异常观察，需要人工复核"
        next_step = "在下方选择异常行，核对字段、时间标签和独立行情来源。"
    elif candidate_count or unknown_count:
        title = "发现记录缺口候选或资格未明的观察"
        next_step = "先确认交易日历、股票上市/停牌资格和源文件完整性。"
    elif rows:
        title = "观察到物理记录，但尚不能认证历史完整性"
        next_step = "可以逐条查看原始证据；需要独立权威来源才能完成完整性认证。"
    else:
        title = "本次没有可供复核的观察行"
        next_step = "检查核验范围、分区读取状态和预算；不能据此宣称数据完整。"
    return {
        "status": "V2G2_AUDIT_REVIEW_ONLY",
        "title": title,
        "next_step": next_step,
        "observation_count": len(rows),
        "alert_count": alert_count,
        "candidate_count": candidate_count,
        "unknown_count": unknown_count,
        "confirmed_missing_count": 0,
        "can_download": False,
        "can_repair": False,
        "finance_fault_link_certified": False,
        "market_file_writes": False,
    }


def format_review_text(review: dict) -> str:
    if (type(review) is not dict
            or review.get("can_download") is not False
            or review.get("can_repair") is not False
            or review.get("market_file_writes") is not False):
        raise AuditFlowBlocked("unsafe_review_preview")
    return (
        "只读复核清单\n"
        "观察对象：" + str(review["focus"]) + "\n"
        "物理解释：" + str(review["title"]) + "\n"
        "下一步：" + str(review["next_step"]) + "\n"
        "必要证据：" + str(review["required_evidence"]) + "\n"
        "状态：未认证，禁止自动下载、覆盖、修复或清空原有进度。\n"
        "财务任务故障日志不能直接作为本条历史行情异常的原因。"
    )
