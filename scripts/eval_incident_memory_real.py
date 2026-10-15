#!/usr/bin/env python3
"""真实 LLM × 合成 Reader 的隔离配对评测。原始轨迹仅写 gitignored 私有目录。"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from langgraph_sdk import get_client

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local/phase33"
CASES = ROOT / "scripts/eval_incident_memory_cases/phase33-main-v1.json"
PORTS = {"A": 18043, "B": 18044, "C": 18045}
PLAN_SEED = 330315
SECRET_PATTERN = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+)", re.IGNORECASE)


def private_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, sort_keys=True, indent=2)
        out.write("\n")


def cases() -> list[dict]:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    rows = data["cases"]
    if len(rows) != 12 or len({row["case_id"] for row in rows}) != 12:
        raise ValueError("Golden v1 必须包含 12 个冻结案例")
    for row in rows:
        if not row["user_prompt"].startswith("诊断 Pod ") or row["target_pod"] not in row["user_prompt"]:
            raise ValueError("主实验必须触发正式精确 Pod 检索")
    return rows


def make_plan(phase: str) -> dict:
    if phase in {"formal", "formal2"}:
        rows = cases()
    elif phase == "pilot4":
        rows = [case for case in cases() if case["case_id"] in
                {"P33-01", "P33-03", "P33-09", "P33-10"}]
    else:
        rows = cases()[:3]
    repeats = 5 if phase in {"formal", "formal2"} else 2
    seed = PLAN_SEED + {"pilot": 0, "formal": 1, "pilot2": 2,
                        "pilot3": 3, "pilot4": 4, "formal2": 5}[phase]
    rng = random.Random(seed)
    pairs = []
    for row in rows:
        for iteration in range(1, repeats + 1):
            order = list("ABC")
            rng.shuffle(order)
            pairs.append({"pair_id": f"{row['case_id']}-{iteration}",
                          "case_id": row["case_id"], "iteration": iteration,
                          "arm_order": order})
    rng.shuffle(pairs)
    return {"phase": phase, "seed": seed,
            "fixture_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
            "planned_runs": len(pairs) * 3, "pairs": pairs}


def env(arm: str) -> dict:
    return dict(line.split("=", 1) for line in (PRIVATE / f"env-{arm}").read_text().splitlines()
                if "=" in line)


def safe_messages(messages: list[dict], secrets: list[str]) -> list[dict]:
    output = []
    for message in messages:
        row = {key: message.get(key) for key in
               ("type", "name", "id", "content", "status", "tool_call_id",
                "tool_calls", "usage_metadata", "response_metadata") if key in message}
        raw = json.dumps(row, ensure_ascii=False)
        for value in secrets:
            if value and value in raw:
                raise RuntimeError("secret_exposure_detected")
        if SECRET_PATTERN.search(raw):
            raise RuntimeError("credential_pattern_detected")
        output.append(row)
    return output


async def execute_one(entry: dict, row: dict, arm: str, map_lock: asyncio.Lock,
                      secrets: list[str], phase: str) -> dict:
    run_id = f"{phase}-{entry['pair_id']}-{arm}"
    start = time.monotonic()
    output = {"run_id": run_id, "pair_id": entry["pair_id"],
              "case_id": row["case_id"], "iteration": entry["iteration"],
              "arm": arm, "arm_order": entry["arm_order"],
              "status": "failed", "error_code": None, "thread_id": None}
    try:
        values = env(arm)
        client = get_client(url=f"http://127.0.0.1:{PORTS[arm]}",
                            api_key=values["DEMO_API_TOKEN"])
        thread = (await client.threads.create())["thread_id"]
        output["thread_id"] = thread
        async with map_lock:
            path = PRIVATE / "thread-map.json"
            mapping = json.loads(path.read_text(encoding="utf-8"))
            mapping[thread] = row["case_id"]
            private_write(path, mapping)
        final_state = {}
        end_status = None
        async for part in client.runs.stream(
                thread, "agent", input={"messages": [{"type": "human",
                                                       "content": row["user_prompt"]}]},
                stream_mode=["values", "updates"], stream_resumable=True):
            if part.event == "values" and isinstance(part.data, dict):
                final_state = part.data
            elif part.event == "end":
                end_status = part.data.get("status") if isinstance(part.data, dict) else str(part.data)
            elif part.event == "error":
                output["error_code"] = "aegra_error_event"
        messages = safe_messages(final_state.get("messages") or [], secrets)
        calls = [call for message in messages if message.get("type") == "ai"
                 for call in message.get("tool_calls") or []]
        ai = [message for message in messages if message.get("type") == "ai"
              and message.get("name") == "triage_llm"]
        answer = next((str(message.get("content", "")) for message in reversed(messages)
                       if message.get("type") == "ai" and not message.get("tool_calls")), "")
        references = final_state.get("memory_references") or []
        output.update({
            "status": "completed" if end_status == "success" and answer else "failed",
            "error_code": output["error_code"] or (None if end_status == "success" and answer
                                                   else "missing_final_answer"),
            "end_status": end_status,
            "memory_retrieval_status": final_state.get("memory_retrieval_status"),
            "memory_reference_ids": [ref.get("memory_id") for ref in references],
            "injected": "历史案例参考（非当前证据）" in answer,
            "tool_calls": [{"name": call.get("name"), "args": call.get("args"),
                            "id": call.get("id")} for call in calls],
            "tool_count": len(calls),
            "pods_get_count": sum(call.get("name") == "pods_get" for call in calls),
            "llm_decisions": len(ai),
            "usage": {"input_tokens": sum((m.get("usage_metadata") or {}).get("input_tokens", 0)
                                          for m in ai),
                      "output_tokens": sum((m.get("usage_metadata") or {}).get("output_tokens", 0)
                                           for m in ai)},
            "answer": answer,
        })
        private_write(PRIVATE / phase / "traces" / f"{run_id}.json",
                      {"run_id": run_id, "messages": messages,
                       "memory_retrieval_status": output["memory_retrieval_status"],
                       "memory_references": references,
                       "end_status": end_status})
    except Exception as exc:
        output["error_code"] = ("secret_exposure_detected" if "secret_exposure" in str(exc)
                                else type(exc).__name__)
        if output["error_code"] == "secret_exposure_detected":
            raise
    output["latency_ms"] = round((time.monotonic() - start) * 1000)
    return output


async def run_phase(phase: str, concurrency: int) -> None:
    plan_path = PRIVATE / f"plan-{phase}.json"
    if not plan_path.exists():
        private_write(plan_path, make_plan(phase))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan != make_plan(phase):
        raise SystemExit("已冻结计划与当前 Golden 不一致")
    rows = {row["case_id"]: row for row in cases()}
    output_path = PRIVATE / phase / "runs.json"
    existing = json.loads(output_path.read_text()) if output_path.exists() else []
    by_id = {row["run_id"]: row for row in existing}
    secrets = [env("A")[key] for key in ("LLM_API_KEY", "DEMO_API_TOKEN",
                                         "INCIDENT_MEMORY_PROVENANCE_SECRET")]
    sem = asyncio.Semaphore(concurrency)
    map_lock = asyncio.Lock()
    save_lock = asyncio.Lock()

    async def task(entry: dict, arm: str) -> None:
        run_id = f"{phase}-{entry['pair_id']}-{arm}"
        if run_id in by_id:
            return
        async with sem:
            result = await execute_one(entry, rows[entry["case_id"]], arm,
                                       map_lock, secrets, phase)
        async with save_lock:
            by_id[run_id] = result
            private_write(output_path, sorted(by_id.values(), key=lambda item: item["run_id"]))
            print(json.dumps({"run_id": run_id, "status": result["status"],
                              "error_code": result["error_code"],
                              "retrieval": result.get("memory_retrieval_status"),
                              "injected": result.get("injected"),
                              "latency_ms": result["latency_ms"]}), flush=True)

    # Arm sequence is frozen within each pair. Pairs may run concurrently.
    async def pair_task(entry: dict) -> None:
        for arm in entry["arm_order"]:
            await task(entry, arm)

    await asyncio.gather(*(pair_task(entry) for entry in plan["pairs"]))


def score(phase: str) -> dict:
    rows = json.loads((PRIVATE / phase / "runs.json").read_text())
    gold = {case["case_id"]: case for case in cases()}
    scored = []
    for row in rows:
        case = gold[row["case_id"]]
        answer = row.get("answer", "")
        state = case["expected_current_state"]
        evidence = row.get("pods_get_count", 0) > 0
        state_correct = (state in answer if state != "unverified" else
                         any(term in answer for term in ("无法", "未取得", "未核验", "403")))
        not_ready = case["expected_ready"] is False and state == "Running"
        false_healthy = not_ready and any(term in answer for term in ("完全健康", "一切正常", "已恢复健康"))
        overclaim = any(term in answer and not any(neg in answer[max(0, answer.index(term)-15):answer.index(term)]
                                                     for neg in ("不能", "无法", "未", "不应"))
                        for term in case["forbidden_causal_claims"])
        stale = case["expected_uid_relation"] == "new" and row.get("injected") and (
            "同一 UID" in answer or "同一实例" in answer)
        row_score = {"run_id": row["run_id"], "case_id": row["case_id"],
                     "arm": row["arm"], "completed": row["status"] == "completed",
                     "diagnosis_correct_auto": bool(evidence and state_correct and not false_healthy
                                                    and not overclaim and not stale),
                     "state_mention": state_correct, "false_healthy_auto": false_healthy,
                     "causal_overclaim_auto": overclaim, "stale_uid_error_auto": stale,
                     "reason": "规则初筛，需独立人工/盲审复核高风险与分歧"}
        scored.append(row_score)
    private_write(PRIVATE / phase / "scores.json", scored)
    by_arm = defaultdict(list)
    for result in scored:
        by_arm[result["arm"]].append(result)
    summary = {arm: {"planned": len(items),
                     "completed": sum(item["completed"] for item in items),
                     "diagnosis_correct_auto": sum(item["diagnosis_correct_auto"] for item in items),
                     "false_healthy_auto": sum(item["false_healthy_auto"] for item in items),
                     "causal_overclaim_auto": sum(item["causal_overclaim_auto"] for item in items)}
               for arm, items in by_arm.items()}
    for arm in "ABC":
        arm_rows = [row for row in rows if row["arm"] == arm]
        summary.setdefault(arm, {})
        summary[arm].update({"hits": sum(row.get("memory_retrieval_status") == "hits"
                                         for row in arm_rows),
                             "injected": sum(bool(row.get("injected")) for row in arm_rows),
                             "median_latency_ms": statistics.median(row["latency_ms"] for row in arm_rows)
                             if arm_rows else None,
                             "mean_tool_count": statistics.mean(row.get("tool_count", 0)
                                                                for row in arm_rows) if arm_rows else None})
    private_write(PRIVATE / phase / "summary.json", summary)
    return summary


def analyze(phase: str) -> dict:
    """ITT 为主；配对差和 bootstrap 区间只作探索性描述。"""
    rows = json.loads((PRIVATE / phase / "runs.json").read_text())
    scores = json.loads((PRIVATE / phase / "scores.json").read_text())
    plan = json.loads((PRIVATE / f"plan-{phase}.json").read_text())
    score_by_id = {item["run_id"]: item for item in scores}
    gold = {case["case_id"]: case for case in cases()}
    by_pair = defaultdict(dict)
    by_arm = defaultdict(list)
    for row in rows:
        by_pair[row["pair_id"]][row["arm"]] = row
        by_arm[row["arm"]].append(row)

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction + 0.999999)))]

    def bootstrap(deltas: list[float]) -> dict:
        if not deltas:
            return {"mean": None, "ci95": None, "n": 0}
        rng = random.Random(330399)
        samples = [statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000)]
        return {"mean": round(statistics.mean(deltas), 4),
                "ci95": [round(percentile(samples, 0.025), 4),
                         round(percentile(samples, 0.975), 4)],
                "n": len(deltas), "interpretation": "exploratory_pair_bootstrap"}

    def case_cluster_bootstrap(values: list[tuple[str, float]]) -> dict:
        grouped = defaultdict(list)
        for case_id, value in values:
            grouped[case_id].append(value)
        if not grouped:
            return {"mean": None, "ci95": None, "case_clusters": 0}
        means = [statistics.mean(group) for group in grouped.values()]
        rng = random.Random(330400)
        sampled = [statistics.mean(rng.choices(means, k=len(means)))
                   for _ in range(2000)]
        return {"mean": round(statistics.mean(means), 4),
                "ci95": [round(percentile(sampled, 0.025), 4),
                         round(percentile(sampled, 0.975), 4)],
                "case_clusters": len(means),
                "interpretation": "exploratory_case_cluster_bootstrap"}

    arms = {}
    for arm in "ABC":
        group = by_arm[arm]
        completed = [row for row in group if row["status"] == "completed"]
        arm_scores = [score_by_id[row["run_id"]] for row in group]
        latency = [row["latency_ms"] for row in group]
        tokens = [row.get("usage") for row in completed]
        arms[arm] = {
            "planned": len(plan["pairs"]), "attempted": len(group),
            "completed": len(completed), "failed": len(group) - len(completed),
            "retrieval_hits": sum(row.get("memory_retrieval_status") == "hits" for row in group),
            "actual_injection": sum(bool(row.get("injected")) for row in group),
            "target_pods_get": sum(any(call.get("name") == "pods_get" and
                                       call.get("args", {}).get("name") ==
                                       gold[row["case_id"]]["target_pod"]
                                       for call in row.get("tool_calls", [])) for row in group),
            "auto_diagnosis_correct_itt": sum(s["diagnosis_correct_auto"] for s in arm_scores),
            "auto_causal_overclaim": sum(s["causal_overclaim_auto"] for s in arm_scores),
            "auto_false_healthy": sum(s["false_healthy_auto"] for s in arm_scores),
            "auto_stale_uid_error": sum(s["stale_uid_error_auto"] for s in arm_scores),
            "latency_ms_p50": percentile(latency, 0.5),
            "latency_ms_p95": percentile(latency, 0.95),
            "mean_tool_count": round(statistics.mean(row.get("tool_count", 0) for row in group), 3)
            if group else None,
            "mean_pods_get_count": round(statistics.mean(row.get("pods_get_count", 0)
                                                           for row in group), 3) if group else None,
            "mean_llm_decisions": round(statistics.mean(row.get("llm_decisions", 0)
                                                          for row in group), 3) if group else None,
            "mean_input_tokens_completed": round(statistics.mean(item["input_tokens"]
                                                                    for item in tokens), 1) if tokens else None,
            "mean_output_tokens_completed": round(statistics.mean(item["output_tokens"]
                                                                     for item in tokens), 1) if tokens else None,
            "missing_usage_completed": sum(not row.get("usage") for row in completed),
            "error_codes": dict(Counter(row.get("error_code") for row in group
                                        if row["status"] != "completed")),
        }
    pairs = {}
    for other in "BC":
        aligned = [(pair["A"], pair[other]) for pair in by_pair.values()
                   if "A" in pair and other in pair]
        pairs[other + "-A"] = {
            "auto_correct_delta": bootstrap([
                int(score_by_id[b["run_id"]]["diagnosis_correct_auto"])
                - int(score_by_id[a["run_id"]]["diagnosis_correct_auto"])
                for a, b in aligned]),
            "latency_ms_delta": bootstrap([b["latency_ms"] - a["latency_ms"]
                                            for a, b in aligned]),
            "tool_count_delta": bootstrap([b.get("tool_count", 0) - a.get("tool_count", 0)
                                             for a, b in aligned]),
            "input_token_delta_completed_pairs": bootstrap([
                b["usage"]["input_tokens"] - a["usage"]["input_tokens"]
                for a, b in aligned if a.get("usage") and b.get("usage")]),
            "case_cluster_auto_correct_delta": case_cluster_bootstrap([
                (a["case_id"], int(score_by_id[b["run_id"]]["diagnosis_correct_auto"])
                 - int(score_by_id[a["run_id"]]["diagnosis_correct_auto"]))
                for a, b in aligned]),
            "case_cluster_input_token_delta_completed": case_cluster_bootstrap([
                (a["case_id"], b["usage"]["input_tokens"] - a["usage"]["input_tokens"])
                for a, b in aligned if a.get("usage") and b.get("usage")]),
            "case_cluster_latency_ms_delta": case_cluster_bootstrap([
                (a["case_id"], b["latency_ms"] - a["latency_ms"])
                for a, b in aligned]),
        }
    per_case = {}
    for case in cases():
        cid = case["case_id"]
        per_case[cid] = {arm: {
            "planned": 5 if phase in {"formal", "formal2"} else 2,
            "completed": sum(row["status"] == "completed" for row in by_arm[arm]
                             if row["case_id"] == cid),
            "auto_correct": sum(score_by_id[row["run_id"]]["diagnosis_correct_auto"]
                                for row in by_arm[arm] if row["case_id"] == cid),
        } for arm in "ABC"}
    blind = []
    for row in rows:
        case = gold[row["case_id"]]
        blind.append({"anonymous_id": hashlib.sha256(row["run_id"].encode()).hexdigest()[:16],
                      "case_id": row["case_id"], "gold_state": case["expected_current_state"],
                      "gold_ready": case["expected_ready"],
                      "uid_relation": case["expected_uid_relation"],
                      "forbidden_claims": case["forbidden_causal_claims"],
                      "answer": row.get("answer", ""),
                      "synthetic_tool_responses": case["mock_tool_responses"],
                      "completed": row["status"] == "completed"})
    random.Random(330398).shuffle(blind)
    private_write(PRIVATE / phase / "blind-review.json", blind)
    analysis = {"phase": phase, "evidence_level": "automatic_rules_not_human_review",
                "human_review": "HUMAN_REVIEW_NOT_RUN", "plan_seed": plan["seed"],
                "fixture_sha256": plan["fixture_sha256"], "arms": arms,
                "paired": pairs, "per_case": per_case,
                "blind_rows": len(blind), "notes": [
                    "ITT 分母包含全部计划 Run；失败不从准确率分母删除。",
                    "规则判分是筛查，不能替代独立人工盲审；bootstrap 区间为探索性。",
                    "后端历史引用展示与模型推理利用必须分开解释。"]}
    private_write(PRIVATE / phase / "analysis.json", analysis)
    return analysis


def finalize_metadata(phase: str) -> dict:
    """给已完成的私有逐 Run 数据补齐固定源码/配置/种子指纹。"""
    path = PRIVATE / phase / "runs.json"
    rows = json.loads(path.read_text())
    plan = json.loads((PRIVATE / f"plan-{phase}.json").read_text())
    config = PRIVATE / "config-fingerprint.json"
    sources = {
        "graph_sha256": ROOT / "server/src/kube_triage/graph.py",
        "mock_reader_sha256": ROOT / "scripts/spikes/phase3_memory/phase33_real_model_mock.py",
        "golden_sha256": CASES,
    }
    hashes = {name: hashlib.sha256(source.read_bytes()).hexdigest()
              for name, source in sources.items()}
    if hashes["golden_sha256"] != plan["fixture_sha256"]:
        raise ValueError("Golden 运行后已变化，拒绝补录")
    seed_hashes = {arm: hashlib.sha256((PRIVATE / f"scripted-seed-{arm}.json").read_bytes()).hexdigest()
                   for arm in "BC"}
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    for row in rows:
        row.update({"baseline_sha": "856a462d4494e16b65a1dc7f44dd14715775f869",
                    "model_config_fingerprint_sha256": config_hash,
                    "source_fingerprints": hashes,
                    "golden_fixture_sha256": plan["fixture_sha256"],
                    "memory_seed_sha256": seed_hashes.get(row["arm"]),
                    "memory_schema_version": 1 if row["arm"] in "BC" else None,
                    "harness_attempts": 1,
                    "provider_internal_attempts": None,
                    "queue_ms": None, "first_response_ms": None})
    private_write(path, rows)
    return {"phase": phase, "runs": len(rows), "source_fingerprints": hashes,
            "config_fingerprint_sha256": config_hash,
            "seed_fingerprint_sha256": seed_hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "run", "score", "analyze", "finalize"])
    parser.add_argument("--phase", choices=["pilot", "pilot2", "pilot3", "pilot4",
                                            "formal", "formal2"], default="pilot")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    if args.command == "plan":
        plan = make_plan(args.phase)
        private_write(PRIVATE / f"plan-{args.phase}.json", plan)
        print({"phase": args.phase, "planned_runs": plan["planned_runs"],
               "seed": plan["seed"], "fixture_sha256": plan["fixture_sha256"]})
    elif args.command == "run":
        if not 1 <= args.concurrency <= 6:
            raise SystemExit("并发必须为 1..6")
        asyncio.run(run_phase(args.phase, args.concurrency))
    elif args.command == "score":
        print(json.dumps(score(args.phase), ensure_ascii=False))
    elif args.command == "analyze":
        print(json.dumps(analyze(args.phase), ensure_ascii=False))
    else:
        print(json.dumps(finalize_metadata(args.phase), ensure_ascii=False))


if __name__ == "__main__":
    main()
