#!/usr/bin/env python3
"""Small, real Aegra Agent Protocol evaluation runner. No FakeModel path."""

import argparse
import json
import os
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ALLOWED = {"pods_list_in_namespace", "pods_get", "events_list", "pods_log"}
EVIDENCE = {"pod_container_state", "restart_or_event", "target_event",
            "last_terminated_reason", "pod_running_ready"}
LABELS = {"CrashLoopBackOff", "ImagePullBackOff", "OOMKilled", "no_fault_evidence"}
ERROR_MARKERS = ("决策上限", "调用预算已用尽", "本次诊断未完成", "模型未返回", "无法解析的 Tool Call")


def private_directory(path):
    old = os.umask(0o077)
    try:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    finally:
        os.umask(old)


def write_private(path, value):
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def load_cases(path):
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or {c.get("id") for c in cases} != {
            "crashloop", "imagepull", "oomkilled", "healthy"}:
        raise ValueError("Golden must contain exactly the four Phase 3A cases")
    for case in cases:
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError("Every case needs a neutral question")
        if not re.fullmatch(r"[a-z0-9-]+", case.get("target_pod", "")):
            raise ValueError("Invalid target Pod")
        if case["target_pod"] not in case["question"]:
            raise ValueError("Question must identify the target Pod")
        if case.get("expected_label") not in LABELS:
            raise ValueError("Unknown expected label")
        if not set(case.get("required_evidence", [])) <= EVIDENCE:
            raise ValueError("Unknown evidence key")
        if not case.get("forbidden_claims"):
            raise ValueError("Forbidden claims must be specified")
    return cases


def api(base, token, path, method="GET", body=None, timeout=30):
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=payload, method=method,
        headers={"X-Api-Key": token, **({"Content-Type": "application/json"} if payload else {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def stream_run(base, token, thread_id, question, timeout):
    payload = {"assistant_id": "agent", "stream_mode": ["updates", "values", "messages-tuple"],
               "input": {"messages": [{"role": "human", "content": question}]}}
    request = urllib.request.Request(base + f"/threads/{thread_id}/runs/stream",
        data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
        headers={"X-Api-Key": token, "Content-Type": "application/json",
                 "Accept": "text/event-stream"})
    events = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        kind, lines = "", []
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:"):
                lines.append(line[5:].strip())
            elif not line and (kind or lines):
                events.append({"event": kind})
                kind, lines = "", []
        if kind or lines:
            events.append({"event": kind})
    return events


def message_type(message):
    return str(message.get("type", message.get("role", ""))).lower()


def parse_result(message):
    content = message.get("content", "")
    try:
        outer = json.loads(content) if isinstance(content, str) else content
        if not isinstance(outer, dict) or outer.get("ok") is not True:
            return None
        result = outer.get("result")
        return json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        return None


def valid_call(name, args):
    if name not in ALLOWED or not isinstance(args, dict):
        return False
    if args.get("namespace") != "kube-triage-demo":
        return False
    required = {"namespace"} | ({"name"} if name in {"pods_get", "pods_log"} else set())
    allowed = required | ({"tail", "container"} if name == "pods_log" else set())
    if not required <= args.keys() or not args.keys() <= allowed:
        return False
    if "name" in args and not isinstance(args["name"], str):
        return False
    if "name" in args and not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", args["name"]):
        return False
    if "tail" in args and (type(args["tail"]) is not int or not 1 <= args["tail"] <= 100):
        return False
    return not ("container" in args and (not isinstance(args["container"], str) or not
                re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", args["container"])))


def safe_call(call):
    args = call.get("args", {})
    return {"id": str(call.get("id", ""))[:100], "name": str(call.get("name", ""))[:100],
            "args": {key: value if isinstance(value, (str, int)) and len(str(value)) < 254
                     else "<invalid>" for key, value in args.items() if key in {
                         "namespace", "name", "tail", "container"}} if isinstance(args, dict) else {}}


def usage(messages):
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    found = False
    for message in messages:
        if message_type(message) not in {"ai", "assistant"}:
            continue
        data = message.get("usage_metadata") or message.get("response_metadata", {}).get("token_usage")
        if not isinstance(data, dict):
            continue
        found = True
        for key, alternatives in {"input_tokens": ("input_tokens", "prompt_tokens"),
                                  "output_tokens": ("output_tokens", "completion_tokens"),
                                  "total_tokens": ("total_tokens",)}.items():
            value = next((data[k] for k in alternatives if isinstance(data.get(k), int)), 0)
            total[key] += value
    return total if found else None


def inspect_messages(messages, case):
    calls = [call for m in messages if message_type(m) in {"ai", "assistant"}
             for call in m.get("tool_calls", [])]
    tools = [m for m in messages if message_type(m) == "tool"]
    final = next((m.get("content", "") for m in reversed(messages)
                  if message_type(m) in {"ai", "assistant"} and not m.get("tool_calls")), "")
    call_ids = Counter(str(c.get("id", "")) for c in calls)
    tool_ids = Counter(str(t.get("tool_call_id", "")) for t in tools)
    matched = bool(calls) and call_ids == tool_ids and "" not in call_ids
    compliant = all(valid_call(c.get("name"), c.get("args")) for c in calls)
    evidence = set()
    target = case["target_pod"]
    for call in calls:
        if not valid_call(call.get("name"), call.get("args")):
            continue
        tool = next((t for t in tools if t.get("tool_call_id") == call.get("id") and
                     t.get("status") != "error"), None)
        item = parse_result(tool) if tool else None
        if not isinstance(item, dict) or item.get("mock") is not True or item.get("source") != "static-fixture":
            continue
        name, args = call["name"], call["args"]
        if name == "pods_get" and args.get("name") == target and item.get("name") == target:
            status = item.get("status", {})
            containers = status.get("containerStatuses", [])
            if any(c.get("state", {}).get("waiting", {}).get("reason") in {
                    "CrashLoopBackOff", "ImagePullBackOff"} for c in containers):
                evidence.add("pod_container_state")
            if any(c.get("restartCount", 0) > 0 for c in containers):
                evidence.add("restart_or_event")
            if any(c.get("lastState", {}).get("terminated", {}).get("reason") == "OOMKilled"
                   for c in containers):
                evidence.add("last_terminated_reason")
            if status.get("phase") == "Running" and containers and all(
                    c.get("ready") is True for c in containers):
                evidence.add("pod_running_ready")
        if name == "events_list":
            related = [event for event in item.get("events", [])
                       if event.get("involvedObject", {}).get("name") == target]
            if any(event.get("type") == "Warning" for event in related):
                evidence.update({"target_event", "restart_or_event"})
    return {"tool_calls": [safe_call(c) for c in calls], "tool_call_count": len(calls),
            "model_decisions": sum(message_type(m) in {"ai", "assistant"} and
                                   m.get("name") == "triage_llm" for m in messages),
            "tool_message_match": matched, "tool_selection_compliant": compliant,
            "tool_success_count": sum(t.get("status") != "error" and parse_result(t) is not None
                                      for t in tools), "evidence_keys": sorted(evidence),
            "evidence_sufficient": set(case["required_evidence"]) <= evidence,
            "budget_or_error_answer": any(marker in str(final) for marker in ERROR_MARKERS),
            "final_answer": final, "token_usage": usage(messages)}


def summarize(rows, planned):
    completed = [r for r in rows if r["run_status"] == "success"]
    durations = [r["elapsed_seconds"] for r in rows if r.get("elapsed_seconds") is not None]
    return {"planned": planned, "recorded": len(rows), "completed": len(completed),
            "failed": sum(r["run_status"] == "fail" for r in rows),
            "blocked": sum(r["run_status"] == "blocked" for r in rows),
            "tool_protocol_pass": sum(r.get("tool_message_match") is True for r in rows),
            "evidence_sufficient": sum(r.get("evidence_sufficient") is True for r in rows),
            "latency_median_seconds": statistics.median(durations) if durations else None,
            "latency_max_seconds": max(durations) if durations else None,
            "token_usage_available": sum(r.get("token_usage") is not None for r in rows),
            "manual_scores": "PENDING until reviews.json is completed"}


def score_reviews(rows, reviews, planned):
    by_key = {(r["case_id"], r["repeat"]): r for r in reviews}
    if len(rows) != planned or any(by_key.get((r["case_id"], r["repeat"]), {}).get(
            "diagnosis_correct") not in {0, 1} or by_key.get((r["case_id"], r["repeat"]), {}).get(
            "grounding_score") not in {0, 1, 2} for r in rows):
        return {"status": "PENDING", "reviewed": sum(
            by_key.get((r["case_id"], r["repeat"]), {}).get("diagnosis_correct") in {0, 1}
            for r in rows), "planned": planned}
    correct = sum(by_key[(r["case_id"], r["repeat"])]["diagnosis_correct"] for r in rows)
    grounding = sum(by_key[(r["case_id"], r["repeat"])]["grounding_score"] for r in rows)
    healthy = [by_key[(r["case_id"], r["repeat"])] for r in rows if r["case_id"] == "healthy"]
    if any(r.get("false_positive") not in {0, 1} for r in healthy):
        return {"status": "PENDING", "reviewed": planned, "planned": planned,
                "reason": "healthy false_positive missing"}
    return {"status": "COMPLETE", "planned": planned,
            "diagnosis_accuracy": correct / planned,
            "average_grounding": grounding / planned,
            "healthy_false_positive_rate": sum(r["false_positive"] for r in healthy) / len(healthy)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("eval/cases.json"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path(".local/eval-runs/phase3a-baseline"))
    parser.add_argument("--api-base", default="http://127.0.0.1:12028")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    if args.repeats < 1 or args.timeout < 10 or args.interval < 0:
        parser.error("Invalid repeats, timeout or interval")
    plan = [(case, repeat) for case in cases for repeat in range(1, args.repeats + 1)]
    if args.max_runs is not None:
        plan = plan[:args.max_runs]
    if args.dry_run:
        print(f"DRY RUN: {len(plan)} cases validated; no Agent Runs or score produced")
        return
    env = {**read_env(args.env_file), **os.environ}
    token = env.get("DEMO_API_TOKEN")
    if not token:
        raise SystemExit("BLOCKED: DEMO_API_TOKEN missing from private env or process")
    model = env.get("LLM_MODEL")
    if env.get("TRIAGE_ENV") != "test" or not model or not env.get("LLM_API_KEY"):
        raise SystemExit("BLOCKED: TRIAGE_ENV=test and existing model credentials required")
    os.umask(0o077)
    private_directory(args.out)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                                text=True, check=True).stdout.strip())
    rows, reviews = [], []
    for case, repeat in plan:
        start = time.monotonic()
        row = {"case_id": case["id"], "repeat": repeat, "model_name": model,
               "git_sha": sha, "git_dirty": dirty, "run_status": "blocked"}
        try:
            thread = api(args.api_base, token, "/threads", "POST", {})
            thread_id = thread["thread_id"]
            events = stream_run(args.api_base, token, thread_id, case["question"], args.timeout)
            state = api(args.api_base, token, f"/threads/{thread_id}/state")
            history = api(args.api_base, token, f"/threads/{thread_id}/history")
            messages = state.get("values", {}).get("messages", [])
            details = inspect_messages(messages, case)
            error_event = any(e["event"] == "error" for e in events)
            okay = (bool(events) and any(e["event"] == "end" for e in events) and
                    not error_event and not state.get("next") and not details["budget_or_error_answer"] and
                    bool(details["final_answer"]))
            try:
                run_list = api(args.api_base, token, f"/threads/{thread_id}/runs")
                latest = run_list[-1] if isinstance(run_list, list) and run_list else {}
                protocol_status = latest.get("status")
                if protocol_status and protocol_status != "success":
                    okay = False
            except (OSError, ValueError):
                protocol_status = None
            row.update({key: value for key, value in details.items() if key != "final_answer"})
            row.update({"thread_id": thread_id, "sse_event_count": len(events),
                        "history_count": len(history), "aegra_run_status": protocol_status,
                        "run_status": "success" if okay else "fail",
                        "final_answer_excerpt": str(details["final_answer"])[:500]})
            write_private(args.out / f"{case['id']}-{repeat}-evidence.json", {
                "thread_id": thread_id, "messages": messages, "sse_events": events,
                "history_count": len(history), "final_answer": details["final_answer"]})
        except (OSError, ValueError, KeyError, TimeoutError) as exc:
            row.update({"run_status": "blocked" if isinstance(exc, OSError) else "fail",
                        "error_type": type(exc).__name__})
        row["elapsed_seconds"] = round(time.monotonic() - start, 3)
        rows.append(row)
        reviews.append({"case_id": case["id"], "repeat": repeat,
                        "diagnosis_correct": None, "grounding_score": None,
                        "false_positive": None,
                        "review_notes": "PENDING: inspect private evidence and cite ToolMessage ID"})
        write_private(args.out / "runs.json", rows)
        write_private(args.out / "reviews.json", reviews)
        write_private(args.out / "summary.json", {
            **summarize(rows, len(plan)), "review_metrics": score_reviews(rows, reviews, len(plan))})
        print(f"{case['id']} #{repeat}: {row['run_status']} ({row['elapsed_seconds']}s)")
        if len(rows) < len(plan):
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
