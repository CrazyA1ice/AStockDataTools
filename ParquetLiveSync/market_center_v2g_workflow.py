"""Pure task-oriented navigation model for the Market Center V2G GUI.

This module is deliberately *not* an executor. It never imports xtquant,
starts an updater, writes progress, or turns a diagnosed error into permission
to retry. All routes point at existing read-only pages and buttons.
"""
from __future__ import annotations

TASKS = (
    {
        "id": "update",
        "title": "更新行情",
        "subtitle": "选范围、预览方案",
        "availability": "仅计划预览",
        "steps": ("选择更新方式与日期", "选择股票和数据类型",
                  "核对只读计划；下载及写入暂不可执行"),
    },
    {
        "id": "audit",
        "title": "检查数据",
        "subtitle": "限定范围、只读核验",
        "availability": "只读可用",
        "steps": ("选择数据核验与日期", "指定股票和所需数据类型",
                  "在安全预检页选择周期并启动受限只读核验",
                  "到核验结果查看观察值和原始证据"),
    },
    {
        "id": "diagnose",
        "title": "处理错误",
        "subtitle": "识别原因、逐项核对",
        "availability": "仅诊断与只读检查",
        "steps": ("查看同轮故障类型和失败批次",
                  "按需检查当前QMT连接；不会下载数据",
                  "核对正式代码版本与财务备份范围",
                  "仅记录处理建议；一键恢复尚未开放"),
    },
    {
        "id": "manage",
        "title": "管理数据",
        "subtitle": "八周期与来源证据",
        "availability": "只读可用",
        "steps": ("查看八周期数据状态及最近更新记录",
                  "注意未经逐周期扫描不能认定完整覆盖",
                  "需要实际核验时转到“检查数据”"),
    },
)
_IDS = frozenset(item["id"] for item in TASKS)


def task_by_id(task_id: str) -> dict:
    """Return an independent copy to keep UI code from mutating routes."""
    for item in TASKS:
        if item["id"] == task_id:
            return {**item, "steps": tuple(item["steps"])}
    raise ValueError("unknown_market_center_task")


def recommended_task(status: dict | None) -> dict:
    """Recommend *navigation*, never a financial action.

    A PARTIAL or failed run is cause for inspection; no receipt is NOT a
    successful run. Historical QMT preflight information is not used as
    evidence of a currently connected service.
    """
    status = status if isinstance(status, dict) else {}
    execution = str(status.get("execution_validation", "")).upper()
    data = str(status.get("data_validation", "")).upper()
    if execution in {"PARTIAL", "FAIL", "FAILED", "ERROR"}:
        return {
            "task_id": "diagnose",
            "reason": "任务执行未全部成功，建议先看本轮故障及检查点。",
            "can_execute_repair": False,
        }
    if data in {"PARTIAL", "FAIL", "FAILED", "ERROR"}:
        return {
            "task_id": "audit",
            "reason": "数据核验存在异常，建议先限定范围进行只读复核。",
            "can_execute_repair": False,
        }
    if execution in {"", "UNVERIFIED", "UNKNOWN"}:
        return {
            "task_id": "audit",
            "reason": "缺少可用的执行证据，建议先只读核验，不推断更新成功。",
            "can_execute_repair": False,
        }
    return {
        "task_id": "audit",
        "reason": "如需确认历史完整性，可指定股票与周期进行只读核验。",
        "can_execute_repair": False,
    }


def workflow_guide(task_id: str) -> str:
    """A compact page banner, retaining precise safety boundaries."""
    item = task_by_id(task_id)
    return "当前目标：" + item["title"] + "  ·  " + " → ".join(item["steps"])


def allowed_ui_routes() -> tuple[str, ...]:
    return tuple(x["id"] for x in TASKS)


def execution_is_disabled() -> bool:
    """V2G has no production manual download or repair executor."""
    return True
