#!/usr/bin/env python3
"""Issue #12 paired, Mock-only A/B runner. Real runs require separate approval."""

import argparse
import ast
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from collections import Counter
from pathlib import Path

from eval_phase3a import (
    api,
    message_type,
    parse_result,
    read_env,
    stream_run,
    usage,
    valid_call,
    write_private,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = "issue12-blind-v1"
EVIDENCE = {"pod_container_state", "target_log", "target_event", "target_event_weak",
            "pod_running_ready", "target_pod_status"}
ERROR_MARKERS = ("决策上限", "调用预算已用尽", "本次诊断未完成", "模型未返回", "无法解析的 Tool Call")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixtures_sha():
    digest = hashlib.sha256()
    directory = ROOT / "server/src/kube_triage/fixtures/issue12"
    for path in sorted(directory.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prompt_sha(arm):
    tree = ast.parse((ROOT / "server/src/kube_triage/prompts.py").read_text(encoding="utf-8"))
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign) and len(node.targets) == 1 and
              isinstance(node.targets[0], ast.Name) and node.targets[0].id in {
                  "SYSTEM_PROMPT", "ISSUE12_CAUSAL_SUFFIX"}}
    actual = values["SYSTEM_PROMPT"] + (values["ISSUE12_CAUSAL_SUFFIX"] if arm == "B" else "")
    return hashlib.sha256(actual.encode()).hexdigest()


def load_cases(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != DATASET or not isinstance(data.get("cases"), list):
        raise ValueError("Unknown dataset version")
    cases = data["cases"]
    ids = [case.get("id") for case in cases]
    if len(cases) != 8 or len(set(ids)) != 8:
        raise ValueError("Blind v1 requires eight unique cases")
    for case in cases:
        target = case.get("target_pod")
        if (not re.fullmatch(r"sample-[a-z]", target or "") or
                not re.fullmatch(r"[a-z]", case.get("id", "")) or
                target not in case.get("question", "") or
                not case.get("ground_truth") or not case.get("forbidden_claims") or
                not set(case.get("required_evidence", [])) <= EVIDENCE):
            raise ValueError("Invalid blind case")
        if any(word in case["question"] for word in ("CrashLoop", "ImagePull", "NotFound", "认证拒绝")):
            raise ValueError("Question leaks diagnosis")
        fixture = ROOT / "server/src/kube_triage/fixtures/issue12" / f"{target}.json"
        item = json.loads(fixture.read_text(encoding="utf-8"))
        if item.get("name") != target or not item.get("containerStatuses"):
            raise ValueError("Missing or inconsistent fixture")
    return cases


def output_path(raw):
    base = ROOT / ".local/eval-runs"
    path = raw if raw.is_absolute() else ROOT / raw
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != ROOT):
        raise ValueError("Symlink output path denied")
    resolved = path.resolve()
    if resolved.parent != base.resolve() or not resolved.name.startswith("issue12-"):
        raise ValueError("Output must be a new .local/eval-runs/issue12-* directory")
    if resolved.exists():
        raise ValueError("Output already exists; never overwrite")
    return resolved


def unpack_result(message):
    if message.get("status") != "success":
        return None
    item = parse_result(message)
    if not isinstance(item, dict) or item.get("mock") is not True or item.get("source") != "static-fixture":
        return None
    return item


def inspect(messages, case):
    calls = [call for msg in messages if message_type(msg) in {"ai", "assistant"}
             for call in msg.get("tool_calls", [])]
    tools = [msg for msg in messages if message_type(msg) == "tool"]
    call_ids = Counter(str(call.get("id", "")) for call in calls)
    tool_ids = Counter(str(msg.get("tool_call_id", "")) for msg in tools)
    paired = bool(calls) and call_ids == tool_ids and "" not in call_ids and all(
        count == 1 for count in call_ids.values())
    compliant = all(valid_call(call.get("name"), call.get("args")) for call in calls)
    results = {msg.get("tool_call_id"): unpack_result(msg) for msg in tools}
    success_ids = [call["id"] for call in calls if results.get(call.get("id")) is not None
                   and call_ids[str(call.get("id"))] == 1 and
                   tool_ids[str(call.get("id"))] == 1]
    evidence = set()
    evidence_ids = {}
    target = case["target_pod"]
    target_uids = {result.get("metadata", {}).get("uid") for call in calls
                   if call.get("name") == "pods_get" and
                   call.get("id") in success_ids and
                   valid_call(call.get("name"), call.get("args")) and
                   call["args"].get("name") == target and
                   (result := results.get(call.get("id"))) and result.get("name") == target}
    target_uids.discard(None)
    seen = Counter()
    unrelated = 0
    for call in calls:
        name, args = call.get("name"), call.get("args")
        if not valid_call(name, args):
            continue
        key = (name, json.dumps(args, sort_keys=True))
        seen[key] += 1
        if name in {"pods_get", "pods_log"} and args.get("name") != target:
            unrelated += 1
        item = results.get(call.get("id")) if call.get("id") in success_ids else None
        if not item:
            continue
        keys = set()
        if name == "pods_get" and args.get("name") == target and item.get("name") == target:
            keys.add("target_pod_status")
            containers = item.get("status", {}).get("containerStatuses", [])
            if any(c.get("state", {}).get("waiting", {}).get("reason") in {
                    "CrashLoopBackOff", "ImagePullBackOff"} for c in containers):
                keys.add("pod_container_state")
            if item.get("status", {}).get("phase") == "Running" and containers and all(
                    c.get("ready") is True for c in containers):
                keys.add("pod_running_ready")
        elif name == "pods_log" and args.get("name") == target and item.get("name") == target:
            if item.get("available") is True and item.get("logs"):
                keys.add("target_log")
        elif name == "events_list":
            for event in item.get("events", []):
                obj = event.get("involvedObject", {})
                if (obj.get("kind") == "Pod" and obj.get("namespace") == "kube-triage-demo"
                        and obj.get("name") == target and event.get("type") == "Warning"):
                    keys.add("target_event" if obj.get("uid") in target_uids
                             else "target_event_weak")
        evidence.update(keys)
        for found in keys:
            evidence_ids.setdefault(found, []).append(call["id"])
    final = next((msg.get("content", "") for msg in reversed(messages)
                  if message_type(msg) in {"ai", "assistant"} and not msg.get("tool_calls")), "")
    decisions = sum(message_type(msg) in {"ai", "assistant"} and
                    msg.get("name") == "triage_llm" for msg in messages)
    return {"tool_call_count": len(calls), "model_decisions": decisions,
            "tool_message_match": paired, "tool_selection_compliant": compliant,
            "tool_success_count": len(success_ids), "tool_failure_count": len(tools) - len(success_ids),
            "duplicate_tool_calls": sum(n - 1 for n in seen.values() if n > 1),
            "unrelated_tool_calls": unrelated, "evidence_keys": sorted(evidence),
            "evidence_tool_call_ids": evidence_ids,
            "evidence_sufficient": set(case["required_evidence"]) <= evidence,
            "budget_exhausted": decisions > 4 or len(calls) > 6 or any(
                marker in str(final) for marker in ERROR_MARKERS),
            "provider_incompatible": any(marker in str(final) for marker in (
                "无法解析的 Tool Call", "模型未返回内容或标准 Tool Call")),
            "final_answer_present": bool(final), "token_usage": usage(messages)}


def rubric(arm, case, repeat):
    return {"arm": arm, "case_id": case["id"], "repeat": repeat,
            "diagnosis_correct": "PENDING", "grounding_score": "PENDING",
            "false_positive": "PENDING", "causal_overclaim": "PENDING",
            "tool_error_handling": "PENDING", "reason": "PENDING",
            "tool_message_ids": [], "model_seen_evidence": "PENDING",
            "independent_ground_truth": case["ground_truth"], "reviewer": "PENDING",
            "reviewed_at": "PENDING"}


def summary(rows, arms, per_arm):
    result = {}
    for arm in arms:
        group = [row for row in rows if row["arm"] == arm]
        times = [row["elapsed_seconds"] for row in group if isinstance(
            row.get("elapsed_seconds"), (int, float))]
        tokens = [row["token_usage"]["total_tokens"] for row in group if isinstance(
            row.get("token_usage"), dict)]
        result[arm] = {"planned": per_arm, "recorded": len(group),
                       "success": sum(row["run_status"] == "success" for row in group),
                       "failed": sum(row["run_status"] == "fail" for row in group),
                       "blocked": sum(row["run_status"] == "blocked" for row in group),
                       "valid_trajectory_denominator": sum(row.get("tool_message_match") is True
                                                           for row in group),
                       "latency_seconds": {"median": statistics.median(times) if times else "UNKNOWN",
                                           "min": min(times) if times else "UNKNOWN",
                                           "max": max(times) if times else "UNKNOWN"},
                       "tokens": {"median": statistics.median(tokens) if tokens else "UNKNOWN",
                                  "min": min(tokens) if tokens else "UNKNOWN",
                                  "max": max(tokens) if tokens else "UNKNOWN"}}
    paired = {(row["case_id"], row["repeat"]): {} for row in rows}
    for row in rows:
        paired[(row["case_id"], row["repeat"])][row["arm"]] = row
    result["paired_recorded"] = sum(all(arm in pair for arm in arms) for pair in paired.values())
    result["quality"] = "PENDING: only rule metrics; no human quality conclusion"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("eval/issue12/blind-v1.json"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--arms", default="A,B")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-runs", type=int, default=48)
    parser.add_argument("--smoke-case", choices=list("abcdefgh"),
                        help="One separately authorized Mock/Provider compatibility Run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorize-model-send", action="store_true")
    parser.add_argument("--env-file-a", type=Path)
    parser.add_argument("--env-file-b", type=Path)
    parser.add_argument("--api-base-a", default="http://127.0.0.1:12128")
    parser.add_argument("--api-base-b", default="http://127.0.0.1:12129")
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args()
    cases_path = args.cases if args.cases.is_absolute() else ROOT / args.cases
    cases = load_cases(cases_path)
    arms = args.arms.split(",")
    if args.repeats < 1 or args.timeout < 10:
        parser.error("Requires positive repeats and timeout >= 10")
    if args.smoke_case:
        if arms != ["A"] or args.repeats != 1:
            parser.error("Smoke requires --arms A --repeats 1 --max-runs 1")
        cases = [case for case in cases if case["id"] == args.smoke_case]
    elif arms != ["A", "B"]:
        parser.error("Formal plan requires paired arms A,B")
    plan = [(arm, case, repeat) for repeat in range(1, args.repeats + 1)
            for case in cases for arm in arms]
    if args.max_runs != len(plan):
        parser.error("--max-runs must equal the complete paired plan")
    try:
        out = output_path(args.out)
    except ValueError as exc:
        parser.error(str(exc))
    dataset_sha = sha256(cases_path)
    fixture_sha = fixtures_sha()
    if args.dry_run:
        print(json.dumps({"status": "DRY RUN; NOT RUN", "dataset_sha256": dataset_sha,
                          "fixture_bundle_sha256": fixture_sha,
                          "graph_sha256": sha256(ROOT / "server/src/kube_triage/graph.py"),
                          "prompt_sha256": {arm: prompt_sha(arm) for arm in arms},
                          "cases": len(cases), "repeats": args.repeats, "arms": arms,
                          "runs_per_arm": len(cases) * args.repeats, "total_runs": len(plan),
                          "model_plan": "gpt-6-luna / Responses API / High requested; verify before real run",
                          "mock_image_sha": "UNKNOWN until Compose build",
                          "output": str(out), "safety": "No key, network, Docker, Thread or Run access"},
                         ensure_ascii=False, indent=2))
        return
    if not args.authorize_model_send:
        parser.error("Real model sending requires a separately approved --authorize-model-send")
    if not args.env_file_a or (not args.smoke_case and not args.env_file_b):
        parser.error("Private env files required for every selected arm")
    envs = [read_env(args.env_file_a)]
    if args.env_file_b and not args.smoke_case:
        envs.append(read_env(args.env_file_b))
    for arm, env in zip(arms, envs, strict=True):
        if (env.get("TRIAGE_ENV") != "test" or env.get("TRIAGE_MOCK_DATASET") != DATASET or
                env.get("EVAL_PROMPT_VARIANT") != arm or env.get("REPAIR_ENABLED") != "false" or
                env.get("LLM_MODEL") != "gpt-6-luna" or
                env.get("EVAL_LUNA_RESPONSES_HIGH") != "true" or
                not env.get("DEMO_API_TOKEN") or not env.get("LLM_API_KEY")):
            parser.error("A/B private env identity or safety configuration invalid")
    fixed = ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "EVAL_LUNA_RESPONSES_HIGH",
             "TRIAGE_MOCK_DATASET")
    if len(envs) == 2 and any(envs[0].get(key) != envs[1].get(key) for key in fixed):
        parser.error("A/B model or dataset mismatch")
    os.umask(0o077)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    graph_sha = sha256(ROOT / "server/src/kube_triage/graph.py")
    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    rows = []
    reviews = []
    for arm, case, repeat in plan:
        env = envs[arms.index(arm)]
        base = args.api_base_a if arm == "A" else args.api_base_b
        started = time.monotonic()
        row = {"arm": arm, "case_id": case["id"], "repeat": repeat,
               "dataset_sha": dataset_sha, "fixture_bundle_sha": fixture_sha,
               "graph_sha": graph_sha,
               "prompt_sha": prompt_sha(arm),
               "git_sha": git_sha, "model_name": env["LLM_MODEL"],
               "model_params": {"api": "Responses", "reasoning_effort_requested": "high",
                                "max_retries": 1, "provider_effort_observed": "UNKNOWN"},
               "thread_id": "NOT RUN", "run_id": "UNKNOWN", "run_status": "blocked"}
        hard_stop = False
        try:
            thread = api(base, env["DEMO_API_TOKEN"], "/threads", "POST", {})
            row["thread_id"] = thread["thread_id"]
            events = stream_run(base, env["DEMO_API_TOKEN"], thread["thread_id"],
                                case["question"], args.timeout)
            state = api(base, env["DEMO_API_TOKEN"], f"/threads/{thread['thread_id']}/state")
            history = api(base, env["DEMO_API_TOKEN"], f"/threads/{thread['thread_id']}/history")
            runs = api(base, env["DEMO_API_TOKEN"], f"/threads/{thread['thread_id']}/runs")
            last = runs[-1] if isinstance(runs, list) and runs else {}
            row["run_id"] = last.get("run_id", "UNKNOWN")
            row["aegra_run_status"] = last.get("status", "UNKNOWN")
            messages = state.get("values", {}).get("messages", [])
            row.update(inspect(messages, case))
            row["run_status"] = ("success" if last.get("status") == "success" and
                                 any(event["event"] == "end" for event in events) and
                                 not any(event["event"] == "error" for event in events) and
                                 not state.get("next") and row["final_answer_present"] and
                                 not row["budget_exhausted"] else "fail")
            hard_stop = (last.get("status") != "success" or
                         any(event["event"] == "error" for event in events) or
                         row["tool_failure_count"] > 0 or row["provider_incompatible"])
            write_private(out / f"{arm}-{case['id']}-{repeat}-private.json", {
                "sse": events, "state": state, "history": history, "runs": runs})
        except (OSError, ValueError, KeyError, TimeoutError) as exc:
            row["run_status"] = "blocked" if isinstance(exc, OSError) else "fail"
            row["error_type"] = type(exc).__name__
            hard_stop = True
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        rows.append(row)
        reviews.append(rubric(arm, case, repeat))
        write_private(out / "runs.json", rows)
        write_private(out / "reviews.json", reviews)
        write_private(out / "summary.json", summary(rows, arms, len(cases) * args.repeats))
        print(f"{arm} {case['id']} #{repeat}: {row['run_status']}")
        if hard_stop:
            print("STOP: Provider, Mock or protocol failure; remaining Runs NOT RUN")
            break


if __name__ == "__main__":
    main()
