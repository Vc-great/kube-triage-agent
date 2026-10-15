#!/usr/bin/env python3
"""Phase 3-4 四组对照的离线计划与冻结题库核验。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "scripts/eval_incident_memory_cases/phase34-targeted-v1.json"
PRIVATE = ROOT / ".local/phase34"
ARMS = {
    "A": {"CONTEXT_SUMMARY_ENABLED": "false", "INCIDENT_MEMORY_READ_ENABLED": "false"},
    "B": {"CONTEXT_SUMMARY_ENABLED": "true", "INCIDENT_MEMORY_READ_ENABLED": "false"},
    "C": {"CONTEXT_SUMMARY_ENABLED": "false", "INCIDENT_MEMORY_READ_ENABLED": "true"},
    "D": {"CONTEXT_SUMMARY_ENABLED": "true", "INCIDENT_MEMORY_READ_ENABLED": "true"},
}
PLAN_SEED = 340315
CONTEXT_BUDGET = 9000


def source_fingerprints() -> dict[str, str]:
    paths = {
        "graph_sha256": ROOT / "server/src/kube_triage/graph.py",
        "mock_reader_sha256": ROOT / "scripts/spikes/phase3_memory/phase34_real_model_mock.py",
        "golden_sha256": GOLDEN,
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def private_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


def cases() -> list[dict]:
    fixture = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if fixture.get("version") != "phase34-targeted-v1":
        raise ValueError("题库版本错误")
    rows = fixture["cases"]
    if len(rows) != 12 or [row["case_id"] for row in rows] != [
            f"P34-{index:02d}" for index in range(1, 13)]:
        raise ValueError("必须有 12 个全新且有序的案例")
    from kube_triage.incident_memory_retrieval import target_pod
    from kube_triage.mcp_client import ALLOWED_TOOLS, NAMESPACE, validate_call

    for row in rows:
        target = row["target_pod"]
        if target_pod(row["user_prompt"]) != target or row["namespace"] != NAMESPACE:
            raise ValueError(f"{row['case_id']} 的目标无法被正式检索器精确识别")
        if set(row["reader_responses"]) != ALLOWED_TOOLS:
            raise ValueError(f"{row['case_id']} Reader Schema 不等于四个白名单工具")
        for name in ALLOWED_TOOLS:
            args = {"namespace": NAMESPACE}
            if name in {"pods_get", "pods_log"}:
                args["name"] = target
            if name == "pods_log":
                args.update(tail=30, container="app")
            validate_call(name, args)
            response = row["reader_responses"][name]
            if type(response.get("ok")) is not bool:
                raise ValueError(f"{row['case_id']} {name} 回执无效")
        for seed in row["memory_seeds"]:
            if not seed.get("observed_uid") or not seed.get("symptom"):
                raise ValueError(f"{row['case_id']} 历史种子不完整")
        if row["historical_conversation"]["rounds"] < 3:
            raise ValueError("历史预设过短")
    if sum(row["historical_conversation"]["rounds"] >= 6 for row in rows) < 6:
        raise ValueError("至少 6 个长历史案例")
    return rows


def make_plan(phase: str) -> dict:
    rows = cases()
    if phase in {"pilot-v1", "pilot-v2", "pilot-v3"}:
        selected = [rows[0], rows[10]]
        repeats = 1
    elif phase in {"formal-v1", "formal-v2"}:
        selected = rows
        repeats = 3
    elif phase in {"fault-v1", "fault-v2"}:
        selected = [rows[index - 1] for index in (7, 8, 9, 10)]
        repeats = 2
    else:
        raise ValueError("未知批次")
    seed = PLAN_SEED + {"pilot-v1": 1, "formal-v1": 2,
                        "fault-v1": 3, "pilot-v2": 4,
                        "formal-v2": 5, "fault-v2": 6,
                        "pilot-v3": 7}[phase]
    randomizer = random.Random(seed)
    pairs = []
    for row in selected:
        for repeat in range(1, repeats + 1):
            order = list(ARMS)
            randomizer.shuffle(order)
            pairs.append({"pair_id": f"{row['case_id']}-{repeat}",
                          "case_id": row["case_id"], "repeat": repeat,
                          "arm_order": order})
    randomizer.shuffle(pairs)
    plan = {"phase": phase, "seed": seed,
            "golden_sha256": hashlib.sha256(GOLDEN.read_bytes()).hexdigest(),
            "planned_runs": len(pairs) * 4, "pairs": pairs,
            "arms": ARMS, "context_estimated_total_budget": CONTEXT_BUDGET,
            "history_seed_rule": "same_case_same_deterministic_rounds"}
    if phase in {"pilot-v3", "formal-v2", "fault-v2"}:
        from kube_triage.prompts import MEMORY_READ_POLICY, SYSTEM_PROMPT

        plan["fixed_system_prompt_sha256"] = hashlib.sha256(
            (SYSTEM_PROMPT + MEMORY_READ_POLICY).encode()).hexdigest()
    return plan


def _model_answer(answer: str) -> str:
    if answer.startswith("[{"):
        try:
            blocks = ast.literal_eval(answer)
            if isinstance(blocks, list) and all(isinstance(block, dict) for block in blocks):
                answer = "\n".join(str(block.get("text", "")) for block in blocks)
        except (SyntaxError, ValueError):
            pass
    return answer.split("历史案例参考（非当前证据）", 1)[0]


def score(phase: str) -> dict:
    """自动规则仅作初筛；缺失槽位仍保留在 ITT 分母。"""
    plan = make_plan(phase)
    stored = json.loads((PRIVATE / f"plan-{phase}.json").read_text())
    if stored != plan:
        raise ValueError("计划或 Golden SHA 已漂移")
    path = PRIVATE / phase / "runs.json"
    actual = json.loads(path.read_text()) if path.exists() else []
    audit = defaultdict(list)
    for arm in ARMS:
        audit_path = PRIVATE / f"audit-{arm}.jsonl"
        if not audit_path.exists():
            continue
        for line in audit_path.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("batch") == phase and event.get("thread_id"):
                audit[event["thread_id"]].append(event)
    for row in actual:
        events = audit.get(row.get("thread_id"), [])
        summaries = [item for item in events if item.get("event") == "context_summary"]
        row["audit"] = {
            "gate_a_statuses": [item.get("status") for item in events
                                if item.get("event") == "context_view"],
            "gate_b_statuses": [item.get("status") for item in events
                                if item.get("event") == "context_summary"],
            "memory_injected_max": max((item.get("injected", 0) for item in events
                                        if item.get("event") == "incident_memory_context"),
                                       default=0),
            "memory_context_events": sum(item.get("event") == "incident_memory_context"
                                         for item in events),
            "summary_requests": sum(item.get("summary_calls", 0) for item in summaries),
            "summary_input_tokens_known": sum(item.get("input_tokens") or 0
                                              for item in summaries),
            "summary_output_tokens_known": sum(item.get("output_tokens") or 0
                                               for item in summaries),
            "summary_usage_unknown": any(item.get("summary_calls") and
                                         (item.get("input_tokens") is None or
                                          item.get("output_tokens") is None)
                                         for item in summaries),
        }
    private_write(PRIVATE / phase / "audit-collated.json", {
        row["run_id"]: row["audit"] for row in actual})
    runs = {row["run_id"]: row for row in actual}
    golden = {row["case_id"]: row for row in cases()}
    scored = []
    for pair in plan["pairs"]:
        case = golden[pair["case_id"]]
        for arm in ARMS:
            run_id = f"{phase}-{pair['pair_id']}-{arm}"
            row = runs.get(run_id, {})
            answer = _model_answer(str(row.get("answer", "")))
            expected = case["expected"]
            completed = row.get("status") == "completed" and bool(answer)
            if expected["target_verified"]:
                grounded = row.get("target_proof") is True
                state_match = expected["state"] in answer
                if expected["ready"] is False and expected["state"] == "Running":
                    state_match = state_match and any(term in answer for term in
                                                      ("Ready=false", "Ready=False", "未就绪", "未准备就绪"))
            else:
                grounded = row.get("target_proof") is False
                state_match = any(term in answer for term in
                                  ("未核验", "无法确认", "无法确定", "未找到", "403", "404", "证据不足"))
            false_healthy = (expected["ready"] is False and
                             any(term in answer for term in ("完全健康", "已恢复健康", "一切正常")))
            causal_overclaim = any(term in answer for term in
                                   ("数据库已宕机", "已确认数据库宕机", "唯一根因是数据库"))
            stale_uid = (case["case_id"] in {"P34-02", "P34-08", "P34-11"} and
                         any(term in answer for term in ("同一 UID", "同一实例")))
            wrong_target = (case["case_id"] == "P34-09" and
                            any(term in answer for term in ("目标已核验", "目标 Pod 已核验")))
            completed = completed and not any(term in answer for term in (
                "诊断未完成", "已达到本轮模型决策上限", "上下文超预算",
                "模型未返回内容或标准 Tool Call"))
            correct = bool(completed and grounded and state_match and not (
                false_healthy or causal_overclaim or stale_uid or wrong_target))
            scored.append({"run_id": run_id, "case_id": case["case_id"], "arm": arm,
                           "attempted": run_id in runs, "completed": completed,
                           "auto_correct": correct, "target_grounded": grounded,
                           "state_match": state_match, "false_healthy": false_healthy,
                           "causal_overclaim": causal_overclaim,
                           "stale_uid": stale_uid, "wrong_target": wrong_target,
                           "human_review": "NOT RUN",
                           "evidence_level": "automatic_screen_only"})
    private_write(PRIVATE / phase / "scores.json", scored)
    return analyze(phase, actual, scored, plan)


def analyze(phase: str, actual: list[dict], scored: list[dict], plan: dict) -> dict:
    by_run = {row["run_id"]: row for row in actual}
    by_score = {row["run_id"]: row for row in scored}

    def percentile(values: list[int], proportion: float) -> int | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * proportion))]

    arms = {}
    for arm in ARMS:
        group = [item for item in scored if item["arm"] == arm]
        observed = [by_run[item["run_id"]] for item in group if item["run_id"] in by_run]
        completed = [item for item in observed if by_score[item["run_id"]]["completed"]]
        usage_observed = [item for item in completed if item.get("model_ids") and
                          item.get("usage", {}).get("input_tokens", 0) > 0]
        arms[arm] = {"planned": len(group), "attempted": len(observed),
                     "completed": len(completed), "failed_or_missing": len(group) - len(completed),
                     "auto_correct_itt": sum(item["auto_correct"] for item in group),
                     "false_healthy": sum(item["false_healthy"] for item in group),
                     "causal_overclaim": sum(item["causal_overclaim"] for item in group),
                     "stale_uid": sum(item["stale_uid"] for item in group),
                     "wrong_target": sum(item["wrong_target"] for item in group),
                     "target_proof": sum(item.get("target_proof") is True for item in observed),
                     "wrong_target_success_receipts": sum(item.get("wrong_target_success") is True
                                                          for item in observed),
                     "tool_failures": sum(item.get("tool_failures", 0) for item in observed),
                     "target_pods_get_calls": sum(
                         call.get("name") == "pods_get" and
                         call.get("args", {}).get("name") == next(
                             case["target_pod"] for case in cases()
                             if case["case_id"] == item["case_id"])
                         for item in observed for call in item.get("tool_calls", [])),
                     "retrieval_hits": sum(item.get("memory_retrieval_status") == "hits"
                                           for item in observed),
                     "actual_injection": sum(item.get("audit", {}).get("memory_injected_max", 0) > 0
                                             for item in observed),
                     "memory_budget_zero_injection": sum(
                         item.get("memory_retrieval_status") == "hits" and
                         item.get("audit", {}).get("memory_injected_max", 0) == 0
                         for item in observed),
                     "displayed_references": sum(bool(item.get("memory_reference_displayed"))
                                                 for item in observed),
                     "gate_a_trimmed": sum("trimmed" in item.get("audit", {}).get(
                         "gate_a_statuses", []) for item in observed),
                     "summary_adopted": sum("adopted" in item.get("audit", {}).get(
                         "gate_b_statuses", []) for item in observed),
                     "summary_fallback": sum("fallback" in item.get("audit", {}).get(
                         "gate_b_statuses", []) for item in observed),
                     "summary_ready_checkpoint": sum(item.get("context_summary_status") == "ready"
                                                     for item in observed),
                     "summary_failed_checkpoint": sum(item.get("context_summary_status") == "failed"
                                                      for item in observed),
                     "tool_count_mean": (round(statistics.mean(item.get("tool_count", 0)
                                                                for item in observed), 2)
                                         if observed else None),
                     "llm_decisions_mean": (round(statistics.mean(item.get("llm_decisions", 0)
                                                                    for item in observed), 2)
                                            if observed else None),
                     "logical_provider_requests_lower_bound": sum(item.get("llm_decisions", 0) +
                                                      item.get("audit", {}).get("summary_requests", 0)
                                                      for item in observed),
                     "model_echo_unknown_runs": sum(not item.get("model_ids") for item in observed),
                     "provider_usage_observed_completed": len(usage_observed),
                     "provider_usage_unknown_completed": len(completed) - len(usage_observed),
                     "summary_usage_unknown_runs": sum(item.get("audit", {}).get(
                         "summary_usage_unknown", False) for item in observed),
                     "input_tokens_mean_observed_completed": (round(statistics.mean(
                         item["usage"]["input_tokens"] for item in usage_observed), 1)
                         if usage_observed else None),
                     "output_tokens_mean_observed_completed": (round(statistics.mean(
                         item["usage"]["output_tokens"] for item in usage_observed), 1)
                         if usage_observed else None),
                     "known_input_tokens_mean_completed_including_summary": (
                         round(statistics.mean(item.get("usage", {}).get("input_tokens", 0) +
                                               item.get("audit", {}).get(
                                                   "summary_input_tokens_known", 0)
                                               for item in usage_observed), 1)
                         if usage_observed else None),
                     "known_output_tokens_mean_completed_including_summary": (
                         round(statistics.mean(item.get("usage", {}).get("output_tokens", 0) +
                                               item.get("audit", {}).get(
                                                   "summary_output_tokens_known", 0)
                                               for item in usage_observed), 1)
                         if usage_observed else None),
                     "latency_ms_p50": percentile([item["latency_ms"] for item in observed], .5),
                     "latency_ms_p95": percentile([item["latency_ms"] for item in observed], .95)}
    paired = {}
    for left, right in (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")):
        deltas = []
        by_case = defaultdict(list)
        for pair in plan["pairs"]:
            a = by_score[f"{phase}-{pair['pair_id']}-{left}"]["auto_correct"]
            b = by_score[f"{phase}-{pair['pair_id']}-{right}"]["auto_correct"]
            delta = int(b) - int(a)
            deltas.append(delta)
            by_case[pair["case_id"]].append(delta)
        paired[f"{right}-{left}"] = {"auto_correct_delta_per_planned_run":
                                       round(statistics.mean(deltas), 4) if deltas else None,
                                   "case_clusters": {case: round(statistics.mean(values), 4)
                                                     for case, values in by_case.items()}}
    per_case = {case["case_id"]: {arm: {
        "planned": sum(item["case_id"] == case["case_id"] and item["arm"] == arm for item in scored),
        "completed": sum(item["case_id"] == case["case_id"] and item["arm"] == arm
                         and item["completed"] for item in scored),
        "auto_correct": sum(item["case_id"] == case["case_id"] and item["arm"] == arm
                            and item["auto_correct"] for item in scored)} for arm in ARMS}
                for case in cases()}
    blind = []
    mapping = {}
    selected = set()
    randomizer = random.Random(340398)
    for arm in ARMS:
        group = [item for item in scored if item["arm"] == arm]
        selected.update(item["run_id"] for item in group if not item["auto_correct"])
        selected.update(item["run_id"] for item in randomizer.sample(
            group, min(len(group), max(1, (len(group) + 4) // 5))))
    judge_path = PRIVATE / phase / "judge.json"
    if judge_path.exists():
        judgments = json.loads(judge_path.read_text())
        for item in scored:
            opaque = hashlib.sha256(item["run_id"].encode()).hexdigest()[:16]
            judgment = judgments.get(opaque, {}).get("judge", {})
            if any(judgment.get(key) for key in (
                    "causal_overclaim", "false_healthy", "stale_uid_misleading",
                    "wrong_target_attribution")) or judgment.get("diagnosis_correct") is False:
                selected.add(item["run_id"])
    for item in scored:
        if item["run_id"] not in selected:
            continue
        opaque = hashlib.sha256(item["run_id"].encode()).hexdigest()[:16]
        case = next(row for row in cases() if row["case_id"] == item["case_id"])
        row = by_run.get(item["run_id"], {})
        blind.append({"anonymous_id": opaque, "case_id": item["case_id"],
                      "prompt": case["user_prompt"], "expected": case["expected"],
                      "synthetic_reader_responses": case["reader_responses"],
                      "answer": _model_answer(str(row.get("answer", ""))),
                      "human_diagnosis_correct": None,
                      "human_causal_overclaim": None, "reviewer": None,
                      "reviewed_at": None, "review_status": "NOT RUN"})
        mapping[opaque] = item["run_id"]
    randomizer.shuffle(blind)
    private_write(PRIVATE / phase / "human-review" / "blind.json", blind)
    private_write(PRIVATE / phase / "human-review" / "hidden-map.json", mapping)
    analysis = {"phase": phase, "planned": plan["planned_runs"], "attempted": len(actual),
                "golden_sha256": plan["golden_sha256"], "arms": arms, "paired": paired,
                "per_case": per_case, "blind_rows": len(blind),
                "human_review": "HUMAN_REVIEW_NOT_RUN",
                "quality_evidence": "automatic_screen_only",
                "warning": "规则初筛可有假阳性/假阴性；重复运行不能当独立真实故障。"}
    private_write(PRIVATE / phase / "analysis.json", analysis)
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "plan", "score", "freeze"])
    parser.add_argument("--phase", choices=["pilot-v1", "pilot-v2", "pilot-v3",
                                            "formal-v1", "formal-v2", "fault-v1", "fault-v2"],
                        default="formal-v2")
    args = parser.parse_args()
    plan = make_plan(args.phase)
    if args.command == "plan":
        path = PRIVATE / f"plan-{args.phase}.json"
        if path.exists() and json.loads(path.read_text()) != plan:
            raise SystemExit("已冻结计划与当前题库不一致")
        private_write(path, plan)
    if args.command == "score":
        result = score(args.phase)
        print(json.dumps({"phase": args.phase, "planned": result["planned"],
                          "attempted": result["attempted"],
                          "human_review": result["human_review"]}, ensure_ascii=False))
        return
    if args.command == "freeze":
        path = PRIVATE / ("formal-v2-source-freeze.json" if args.phase == "formal-v2"
                          else "formal-source-freeze.json")
        freeze = {**source_fingerprints(), "context_estimated_total_budget": CONTEXT_BUDGET,
                  "baseline": "c90abdddecc8b288b1392b71c3a326a04afda0ae"}
        if args.phase == "formal-v2":
            freeze["fixed_system_prompt_sha256"] = plan["fixed_system_prompt_sha256"]
        if path.exists() and json.loads(path.read_text()) != freeze:
            raise SystemExit("正式源码冻结文件已存在且内容不同")
        private_write(path, freeze)
        print(json.dumps(freeze, sort_keys=True))
        return
    print(json.dumps({"phase": args.phase, "planned_runs": plan["planned_runs"],
                      "golden_sha256": plan["golden_sha256"],
                      "groups": list(ARMS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
