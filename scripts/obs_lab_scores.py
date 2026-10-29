"""Versioned offline rule checks over saved lab evidence; no network or model calls."""

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from eval_issue12 import (
    FROZEN_DATASET_SHA,
    FROZEN_FIXTURES_SHA,
    fixtures_sha,
    inspect,
    sha256,
)
from eval_metrics import latency, model_messages
from obs_lab_faults import FAULTS, inspect_faults
from obs_lab_verify import decoded, final_answer, history_matches, timestamp

ROOT = Path(__file__).resolve().parents[1]
VERSION = "obs-lab-rules-v1"
TARGETS = {"S01": "e", "S02": "a", "S03": "c", **{f"S0{i}": "a" for i in range(4, 9)},
           "S09": "h", "S10": "g"}
# Necessary lexical markers only, not semantic entailment. Quotation/negation can fool this rule.
ANSWER_MARKERS = {
    "S01": (("ready", "就绪"), ("业务", "端到端", "快照")),
    "S02": (("app_config_path", "配置路径", "配置文件"), ("日志", "log")),
    "S03": (("notfound", "not found", "不存在"), ("镜像", "image")),
    "S04": (("未知", "无法确认", "不能确定", "证据不足"),),
    "S05": (("权限", "403"), ("未知", "无法确认", "不能确认", "未确认", "缺口")),
    "S06": (("日志", "log"), ("未知", "无法确认", "不能确定", "证据不足")),
    "S07": (("app_config_path", "配置路径", "配置文件"), ("日志", "log")),
    "S08": (("app_config_path", "配置路径", "配置文件"), ("日志", "log")),
    "S09": (("ready", "就绪"), ("业务", "端到端", "快照")),
    "S10": (("uid",), ("弱", "无 uid", "缺失", "不确定", "无法"),
            ("根因未知", "根因不明", "无法确认根因", "不能确定根因", "不足以确认根因")),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def current_round(messages):
    start = max((i for i, m in enumerate(messages) if m.get("type", m.get("role")) in
                 {"human", "user"}), default=0)
    return messages[start:]


def turn_evidence(raw):
    """Project actual snapshots to the latest turn, never manufacture a History snapshot."""
    if "prior_run_ids" not in raw:
        return raw
    def snapshot(state):
        return {"values": {"messages": current_round((state or {}).get("values", {}).get("messages", []))}}
    return {**raw, "state": snapshot(raw.get("state")),
            "history": [snapshot(s) for s in raw["history"]] if isinstance(raw.get("history"), list) else None,
            "runs": [r for r in raw.get("runs") or [] if r.get("run_id") not in raw["prior_run_ids"]
                     and r.get("thread_id") == raw.get("thread_id")]}


def frozen_cases():
    path = ROOT / "eval/issue12/blind-v1.json"
    if sha256(path) != FROZEN_DATASET_SHA or fixtures_sha() != FROZEN_FIXTURES_SHA:
        raise ValueError("STOP: frozen Ground Truth/fixtures changed")
    return {c["id"]: c for c in json.loads(path.read_text())["cases"]}


def rule(value, reason, applicable=True):
    return {"status": "UNKNOWN" if value is None else "PASS" if value else "FAIL",
            "value": None if value is None else int(value), "reason": reason,
            "applicable": applicable, "source": "deterministic_rule_check", "version": VERSION}


def score_run(row, raw, case):
    """Natural language checks deliberately test markers, never semantic correctness."""
    messages = (raw.get("state") or {}).get("values", {}).get("messages")
    if not isinstance(messages, list) or not messages:
        return {"rules": {name: rule(None, "state_messages_missing") for name in (
            "tool_protocol_valid", "fault_handled", "evidence_uid_matched",
            "unnecessary_retry", "grounding_rule")}, "diagnosis_correct": "UNKNOWN"}
    details = inspect(messages, case)
    calls, receipts = details["tool_call_count"], details["tool_message_count"]
    paired = details["tool_message_match"] if calls or receipts else None
    history = history_matches(raw["state"], raw.get("history"))
    protocol = rule(paired and history and details["tool_selection_compliant"]
                    and not details["budget_limit_exceeded"] if paired is not None else None,
                    "unique_call_id_pairing_and_saved_history" if history else "history_missing_or_mismatch")
    normalized = [{**m, "content": '{"ok":null}'} if m.get("type", m.get("role")) == "tool"
                  and not isinstance(decoded(m.get("content")), dict) else m for m in messages]
    if paired:
        faults = inspect_faults(normalized, row["scenario_id"])
    else:
        faults = {"records": [], "fault_observed": False, "duplicate_count": None}
    answer = final_answer(messages)
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    # A narrow lexical rule. Presence can be negated or quoted: never diagnosis_correct.
    markers = {"S04": ("超时", "timeout", "未获取", "未取得"),
               "S05": ("403", "权限", "拒绝"),
               "S06": ("unavailable", "不可用", "未获取", "未取得")}
    applicable_fault = row["scenario_id"] in FAULTS
    fault = rule(None, "not_applicable_no_injected_reader_fault", False)
    if applicable_fault:
        found = faults["fault_observed"]
        fault = rule(bool(text) and any(m in text.lower() for m in markers[row["scenario_id"]])
                     if found and paired else None,
                     "fault_observed_and_answer_marker_check; semantic_handling_unverified"
                     if found and paired else "fault_or_pairing_not_verified")
    keys = details["evidence_keys"]
    has_event = "target_event" in keys or "target_event_weak" in keys
    uid = rule(False if details["event_uid_mismatch"] or details["event_uid_invalid"] else
               True if "target_event" in keys else None,
               "strong_target_uid_receipt" if "target_event" in keys else
               "weak_missing_or_conflicting_uid; does_not_grade_answer", has_event)
    sufficient = details["evidence_sufficient"]
    marker_groups = ANSWER_MARKERS[row["scenario_id"]]
    matched = [any(marker in text.lower() for marker in group) for group in marker_groups]
    # Reader-fault cases intentionally lack evidence; admitting that gap is valid grounding.
    basis = sufficient or (applicable_fault and faults["fault_observed"])
    grounding = rule(basis and all(matched) if paired and text else None,
                     "paired_evidence_or_observed_fault_plus_required_answer_markers_only; "
                     "negation_quotation_and_entailment_UNVERIFIED")
    # Repeated parameters alone cannot prove that a retry was unnecessary.
    retry = rule(None, "duplicate_intent_and_temporal_change_not_machine_verifiable"
                 if faults["duplicate_count"] else "no_duplicate_calls", bool(faults["duplicate_count"]))
    return {"rules": {"tool_protocol_valid": protocol, "fault_handled": fault,
                      "evidence_uid_matched": uid, "unnecessary_retry": retry,
                      "grounding_rule": grounding},
            "diagnosis_correct": "UNKNOWN", "judge": "NOT RUN", "human_review": "NOT RUN",
            "ground_truth_sha256": digest(case), "answer_sha256": digest(answer),
            "evidence_keys": keys, "required_evidence_available": sufficient,
            "answer_marker_groups_matched": matched,
            "evidence_tool_call_ids": details["evidence_tool_call_ids"],
            "uid_mismatch_count": details["event_uid_mismatch"],
            "uid_unverified_count": details["event_uid_unverified"],
            "duplicate_count": faults["duplicate_count"],
            "tool_outcomes": dict(Counter(r["outcome"] for r in faults["records"])),
            "usage": model_messages(messages), "native_trace_complete":
            (row.get("cloud") or {}).get("native_trace_complete", "UNKNOWN")}


def evaluate(sources):
    cases = frozen_cases()
    result = {"schema": VERSION, "mode": "offline_read_only", "runs": [], "source_hashes": {}}
    identities = set()
    times = []
    for source in sources:
        source = source.resolve()
        manifest_path = source / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        result["source_hashes"][str(manifest_path)] = sha256(manifest_path)
        for row in manifest["runs"]:
            if row["scenario_id"] not in TARGETS:
                raise ValueError("STOP: unknown scenario")
            identity = (manifest["project_id"], row.get("run_id"))
            if not identity[1] or identity in identities:
                raise ValueError("STOP: missing/duplicate run identity")
            identities.add(identity)
            prefix = f"{row['scenario_id']}-{row['repeat']}"
            raw_path, cloud_path = source / f"{prefix}-private.json", source / f"{prefix}-cloud.json"
            raw = turn_evidence(json.loads(raw_path.read_text()))
            observations = json.loads(cloud_path.read_text())
            hashes = {str(p): sha256(p) for p in (raw_path, cloud_path)}
            result["source_hashes"].update(hashes)
            # Verify trusted identity independently of cached PASS labels. No guessing trace IDs.
            from obs_lab import inspect_run
            from obs_lab_verify import verify_native

            inspected = inspect_run(raw.get("state") or {}, raw.get("runs") or [], raw.get("events") or [])
            if inspected["run_id"] != row["run_id"] or raw.get("thread_id") != row.get("thread_id"):
                raise ValueError("STOP: saved Run/Thread identity mismatch")
            verification_row = {**row, **inspected, "history_tool_pairs_valid": history_matches(
                raw.get("state") or {}, raw.get("history"))}
            if row["scenario_id"] == "S09":
                from obs_lab_context_verify import verify_context_cloud

                native = verify_context_cloud(observations, verification_row, manifest["project_id"])
            else:
                native = verify_native(observations, verification_row, manifest["project_id"])
            if not native["trace_verified"]:
                raise ValueError("STOP: Cloud Trace identity unverified")
            scored = score_run(row, raw, cases[TARGETS[row["scenario_id"]]])
            if row["scenario_id"] == "S09":
                scored["summary_outcomes"] = native.get("summary_outcomes", [])
            scored.update(scenario_id=row["scenario_id"], run_id=row["run_id"],
                          thread_id=row["thread_id"], project_id=manifest["project_id"],
                          trace_id=native["trace_id"], batch_id=manifest["batch_id"],
                          score_timestamp=row["end"],
                          native_trace_complete="PASS" if native["chain_verified"] else "FAIL",
                          source_sha256=digest(hashes))
            root = next((o for o in observations if o.get("id") == native.get("root_id")), {})
            start, end = timestamp(root.get("startTime")), timestamp(root.get("endTime"))
            scored["trace_latency_seconds"] = end - start if (
                start is not None and end is not None and end >= start) else None
            scored["protocol_status"] = inspected["protocol_status"]
            result["runs"].append(scored)
            times.append(row.get("elapsed_seconds"))
    result["latency"] = latency(times)
    result["trace_root_latency"] = latency([r["trace_latency_seconds"] for r in result["runs"]])
    for key in ("n", "missing_count"):
        result["trace_root_latency"][key]["provenance"] = "Cloud root endTime-startTime"
    for key in ("p50", "p95"):
        result["trace_root_latency"][key]["provenance"] = "Cloud root endTime-startTime; descriptive samples"
    result["rule_counts"] = {name: dict(Counter(r["rules"][name]["status"] for r in result["runs"]))
                             for name in ("tool_protocol_valid", "fault_handled", "evidence_uid_matched",
                                          "unnecessary_retry", "grounding_rule")}
    result["run_status_counts"] = dict(Counter(r["protocol_status"] for r in result["runs"]))
    result["tool_outcome_counts"] = dict(sum((Counter(r["tool_outcomes"]) for r in result["runs"]), Counter()))
    result["tool_outcome_denominator"] = sum(result["tool_outcome_counts"].values())
    result["denominators"] = {"runs": len(identities), "scenarios": len({r["scenario_id"] for r in result["runs"]}),
                              "diagnosis_correct_known": 0}
    result["limitations"] = ["descriptive_samples_only", "no_semantic_or_human_correctness_score",
                              "missing_usage_and_latency_are_UNKNOWN", "no_bill_estimate"]
    return result


def upload_plan(result):
    """Data-minimal candidate payloads; stable IDs prevent duplicate creation on retry."""
    scores = []
    for row in result["runs"]:
        for name, item in row["rules"].items():
            identity = [VERSION, row["project_id"], row["batch_id"], row["run_id"], row["trace_id"], name]
            scores.append({"id": digest(identity), "traceId": row["trace_id"],
                           "name": f"{VERSION}.{name}", "dataType": "CATEGORICAL",
                           "value": item["status"], "timestamp": row["score_timestamp"],
                           "source": "API", "environment": "obs-lab",
                           "comment": json.dumps({
                               "source": "deterministic_rule_check", "version": VERSION,
                               "evidence_sha256": row["source_sha256"],
                               "ground_truth_sha256": row.get("ground_truth_sha256"),
                               "applicable": item["applicable"]}, sort_keys=True)})
    projects = sorted({r["project_id"] for r in result["runs"]})
    return {"schema": VERSION, "projects": projects,
            "mode": "approval_required_no_cloud_writes", "scores": scores,
            "max_writes": len(scores), "plan_sha256": digest(scores)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(p.resolve()) for p in args.source):
        parser.error("output must be new and outside historical source directories")
    result = evaluate(args.source)
    result["upload_plan"] = upload_plan(result)
    # Detect mutation during evaluation; original STOP and all source bytes remain untouched.
    if any(sha256(Path(p)) != expected for p, expected in result["source_hashes"].items()):
        raise ValueError("STOP: source evidence changed during evaluation")
    with open(output, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"mode": result["mode"], "denominators": result["denominators"],
                      "candidate_scores": result["upload_plan"]["max_writes"]}))


if __name__ == "__main__":
    main()
