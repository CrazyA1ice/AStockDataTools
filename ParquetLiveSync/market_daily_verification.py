#!/usr/bin/env python3
"""Read only THIS RUN's four captured stage logs and report evidence honestly.

No QMT or Parquet access, no network, and no schedule changes. Missing or
malformed evidence becomes UNVERIFIED, never an implied PASS.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

STAGES = ("EIGHT_PERIODS", "SECTORS", "ADJUSTMENTS_ROTATING", "FINANCIAL_DAILY")
NAMES = {
    "EIGHT_PERIODS": "K线",
    "FINANCIAL_DAILY": "财务",
    "SECTORS": "板块",
    "ADJUSTMENTS_ROTATING": "除权",
}
LABELS = {"PASS": "通过", "PARTIAL": "部分通过",
          "FAIL": "失败", "UNVERIFIED": "未验证", "NOT_RUN": "未运行"}
JSON_KEYS = {
    "EIGHT_PERIODS": "MARKET_EIGHT_PERIOD_SUMMARY=",
    "FINANCIAL_DAILY": "QMT_FINANCIAL_CACHE_IMPORT_SUMMARY=",
    "SECTORS": "MARKET_QMT_EXTRA_SUMMARY=",
    "ADJUSTMENTS_ROTATING": "MARKET_QMT_EXTRA_SUMMARY=",
}
SOURCE_SAMPLE = re.compile(
    r"^MARKET_SOURCE_SAMPLE=(\w+) status=(\w+) agreed=(\d+)/(\d+)\b"
)


def _last_json(text: str, marker: str):
    result = None
    for line in text.splitlines():
        if line.startswith(marker):
            try:
                obj = json.loads(line[len(marker):])
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                result = obj
    return result


def _source_expected(config):
    if not config:
        return set()
    try:
        obj = json.loads(Path(config).read_text(encoding="utf-8-sig"))
        checks = obj.get("minute_cross_checks", {})
        return {name for name, v in checks.items()
                if isinstance(v, dict) and v.get("enabled") is True}
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


def assess(stage: str, exit_code, log_text: str, *, expected_sources=()):
    if stage not in STAGES:
        raise ValueError("Unrecognized stage")
    if exit_code is None:
        return {"execution": "NOT_RUN", "data_validation": "NOT_RUN",
                "cross_validation": "NOT_RUN", "detail": "未执行"}
    if not isinstance(exit_code, int):
        raise ValueError("Invalid stage exit code")
    ran = exit_code == 0
    prefix = JSON_KEYS[stage]
    receipt = _last_json(log_text, prefix)
    result = {"execution": "PASS" if ran else "FAIL",
              "data_validation": "UNVERIFIED" if ran else "FAIL",
              "cross_validation": "UNVERIFIED",
              "detail": "无当次结构化校验回执" if ran else "步骤执行失败，旧数据未据此判为损坏"}
    if not isinstance(receipt, dict):
        return result

    if stage == "EIGHT_PERIODS":
        valid = (receipt.get("status") == "ALL_EIGHT_PERIOD_PHASES_COMPLETE"
                 and receipt.get("applied") is True
                 and not receipt.get("phases_blocked"))
        if not valid:
            result["data_validation"] = "FAIL"
            result["detail"] = "八周期存在未完成阶段或来源未就绪"
        elif ran:
            newly_staged = []
            for line in log_text.splitlines():
                if line.startswith("MARKET_DAILY_STAGED="):
                    try:
                        doc = json.loads(line[len("MARKET_DAILY_STAGED="):])
                        if isinstance(doc, dict):
                            newly_staged.append(doc)
                    except ValueError:
                        continue
            if any(int(x.get("quarantine", 0)) > 0 for x in newly_staged):
                result["data_validation"] = "PARTIAL"
                result["detail"] = "八周期阶段完成，但部分股票被隔离"
            elif newly_staged:
                result["data_validation"] = "PASS"
                result["detail"] = "本轮新增行情完成八周期及日线校验"
            else:
                result["data_validation"] = "UNVERIFIED"
                result["detail"] = "八周期阶段完成，本次无新增行情校验回执"
        samples = []
        for line in log_text.splitlines():
            m = SOURCE_SAMPLE.match(line)
            if m:
                samples.append((m.group(1), m.group(2),
                                int(m.group(3)), int(m.group(4))))
        expected = set(expected_sources)
        if any(status == "PRICE_DISAGREES" for _, status, _, _ in samples):
            result["cross_validation"] = "FAIL"
        elif (expected and samples
              and expected <= {name for name, _, _, _ in samples}
              and all(status == "AGREE" and total > 0 and agreed == total
                      for name, status, agreed, total in samples
                      if name in expected)):
            result["cross_validation"] = "PASS"
        else:
            result["cross_validation"] = "UNVERIFIED"
        if result["cross_validation"] == "PASS":
            result["detail"] += "；已配置的独立分钟源抽样一致"
        elif result["cross_validation"] == "FAIL":
            result["detail"] += "；发现抽样跨源价格差异"
        else:
            result["detail"] += "；本轮无足够跨源抽样通过证据"

    elif stage == "FINANCIAL_DAILY":
        if receipt.get("mode") != "daily" or receipt.get("apply") is not True:
            return result
        pending = receipt.get("pending_total")
        remaining = receipt.get("daily_remaining_unvisited")
        processed = receipt.get("processed")
        scanned = receipt.get("daily_sweep_reached_end")
        result["processed"] = processed
        result["pending_total"] = pending
        result["remaining_unvisited"] = remaining
        result["daily_sweep_reached_end"] = scanned
        incomplete = (receipt.get("source_completeness_verified") is not True)
        if not ran:
            result["data_validation"] = "FAIL"
        elif (any(type(x) is not int or x < 0
                  for x in (pending, remaining, processed))
              or type(scanned) is not bool):
            # Missing or malformed sweep proof must not count as routine.
            result["data_validation"] = "UNVERIFIED"
        elif pending or remaining or not scanned:
            result["data_validation"] = "PARTIAL"
        else:
            result["data_validation"] = "UNVERIFIED" if incomplete else "PASS"
        result["detail"] = (f"本轮校验处理{processed}只；待审{pending}只；"
                            f"未遍历{remaining}只；历史完整性"
                            + ("未验证" if incomplete else "通过"))

    elif stage == "SECTORS":
        sections = receipt.get("sections")
        sector = sections.get("sectors", {}) if isinstance(sections, dict) else {}
        if (ran and isinstance(sector, dict)
                and sector.get("status") in ("CREATED", "UPDATED", "UNCHANGED")
                and isinstance(sector.get("memberships"), int)
                and sector["memberships"] > 0):
            result["data_validation"] = "PASS"
            result["detail"] = ("QMT板块快照校验通过，成员记录"
                                + str(sector["memberships"]) + "条")
        else:
            result["data_validation"] = "FAIL" if not ran else "UNVERIFIED"
            result["detail"] = "板块本次提交无充分有效快照回执"

    elif stage == "ADJUSTMENTS_ROTATING":
        sections = receipt.get("sections")
        adj = sections.get("adjustments", {}) if isinstance(sections, dict) else {}
        processed = adj.get("symbols_processed") if isinstance(adj, dict) else None
        more = adj.get("next_batch_required") if isinstance(adj, dict) else None
        result["processed"] = processed
        result["next_batch_required"] = more
        if ran and type(processed) is int and processed > 0 and type(more) is bool:
            result["data_validation"] = "PARTIAL" if more else "PASS"
            result["detail"] = (f"QMT除权本批处理{processed}只；"
                                + ("后续仍有批次" if more else "本轮遍历已到末尾"))
        else:
            result["data_validation"] = "FAIL" if not ran else "UNVERIFIED"
            result["detail"] = "除权本次无充分批次校验回执"
    # There are currently no certified independent financial, sector, or
    # adjustment sources. Preserve UNVERIFIED even when their QMT commit passed.
    return result


def routine_continuation(run: dict, sections: dict, execution: str,
                         quality: str, cross: str) -> bool:
    """True only for proven normal finance/adjustment rotation.

    This is an operational exit policy, NOT a certification of financial
    history completeness, source provenance or cross-source agreement.
    Unknown evidence remains non-routine; no data-quality flags are rewritten.
    """
    raw = run.get("stage_records")
    completed = run.get("steps_completed")
    if (execution != "PASS" or quality != "PARTIAL" or cross == "FAIL"
            or type(raw) is not dict or type(completed) is not list
            or len(completed) != len(STAGES) or set(completed) != set(STAGES)
            or run.get("errors") != []):
        return False
    for stage in STAGES:
        record = raw.get(stage)
        section = sections.get(stage)
        if (type(record) is not dict or type(record.get("exit_code")) is not int
                or record["exit_code"] != 0 or type(section) is not dict
                or section.get("execution") != "PASS"
                or section.get("cross_validation") == "FAIL"):
            return False
    if (sections["EIGHT_PERIODS"]["data_validation"] != "PASS"
            or sections["SECTORS"]["data_validation"] != "PASS"):
        return False
    finance = sections["FINANCIAL_DAILY"]
    adjust = sections["ADJUSTMENTS_ROTATING"]
    if (finance["data_validation"] not in ("PASS", "PARTIAL")
            or adjust["data_validation"] not in ("PASS", "PARTIAL")
            or not (finance["data_validation"] == "PARTIAL"
                    or adjust["data_validation"] == "PARTIAL")):
        return False
    if finance["data_validation"] == "PARTIAL":
        if (any(type(finance.get(k)) is not int or finance[k] < 0
                for k in ("processed", "pending_total", "remaining_unvisited"))
                or type(finance.get("daily_sweep_reached_end")) is not bool
                or not (finance["pending_total"] > 0
                        or finance["remaining_unvisited"] > 0
                        or not finance["daily_sweep_reached_end"])):
            return False
    if adjust["data_validation"] == "PARTIAL":
        if (type(adjust.get("processed")) is not int
                or adjust["processed"] <= 0
                or adjust.get("next_batch_required") is not True):
            return False
    return True


def report(run, *, expected_sources=()):
    raw = run.get("stage_records", {})
    sections = {}
    for stage in STAGES:
        item = raw.get(stage)
        if not item:
            sections[stage] = assess(stage, None, "", expected_sources=expected_sources)
            continue
        if (stage == "FINANCIAL_DAILY"
                and item.get("status") == "DEFERRED_CUTOFF"
                and item.get("exit_code") == 87):
            # A bounded evening job has intentionally not started the finance
            # batch. This is a reported continuation, not data corruption.
            sections[stage] = {
                "execution": "DEFERRED",
                "data_validation": "UNVERIFIED",
                "cross_validation": "UNVERIFIED",
                "detail": "财务因晚间时间预算不足顺延下次20:05，原游标保留",
            }
            continue
        file = Path(item["log_path"])
        try:
            log = file.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            log = ""
        sections[stage] = assess(
            stage, int(item["exit_code"]), log, expected_sources=expected_sources)
    failures = sum(s["execution"] == "FAIL" for s in sections.values())
    completed = sum(s["execution"] == "PASS" for s in sections.values())
    if failures or completed != len(STAGES):
        execution = "PARTIAL" if completed else "FAIL"
    else:
        execution = "PASS"
    cross = ("FAIL" if any(s["cross_validation"] == "FAIL" for s in sections.values())
             else "UNVERIFIED" if any(
                 s["cross_validation"] != "PASS" for s in sections.values())
             else "PASS")
    quality = ("FAIL" if any(s["data_validation"] == "FAIL" for s in sections.values())
               else "PARTIAL" if any(
                   s["data_validation"] == "PARTIAL" for s in sections.values())
               else "UNVERIFIED" if any(
                   s["data_validation"] != "PASS" for s in sections.values())
               else "PASS")
    routine = routine_continuation(run, sections, execution, quality, cross)
    # Keep notification concise; report true data/cross evidence separately.
    message = (f"执行{LABELS[execution]}({completed}/4)；"
               f"数据校验{LABELS[quality]}；跨源验证{LABELS[cross]}。")
    details = []
    for stage in STAGES:
        item = sections[stage]
        message += (f" {NAMES[stage]}：数据{LABELS[item['data_validation']]}，"
                    f"跨源{LABELS[item['cross_validation']]}；")
        if item["data_validation"] != "PASS" or item["cross_validation"] == "FAIL":
            details.append(f"{NAMES[stage]}：{item['detail']}")
    if routine:
        message = "本轮更新执行完成，财务/除权正常轮换；历史待审和未认证状态保留。 " + message
    if details:
        message += " 说明：" + "；".join(details)
    errors = run.get("errors")
    if isinstance(errors, list) and errors:
        message += "；本次错误：" + str(errors[0])[:110]
    message += "；财务/板块/除权未实现独立跨源核验。"
    return {"format": "qmt_daily_verification_v1",
            "execution": execution, "data_validation": quality,
            "cross_validation": cross, "sections": sections,
            "routine_continuation": routine,
            "notification_text": message[:620],
            "warning": "PASS refers only to supported local/phase checks; cross PASS is sampled, not full universe"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--sources-config", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.run_json.read_text(encoding="utf-8-sig"))
    result = report(payload, expected_sources=_source_expected(args.sources_config))
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print("MARKET_DAILY_VERIFICATION_SUMMARY=" + json.dumps(
        {"execution": result["execution"],
         "data_validation": result["data_validation"],
         "cross_validation": result["cross_validation"]},
        ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
