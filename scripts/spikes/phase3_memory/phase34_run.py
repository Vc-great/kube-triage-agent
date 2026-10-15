#!/usr/bin/env python3
"""经真实 Aegra SDK 准备可比历史、脚本化 Memory 种子并执行合成 Reader 诊断。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time

from eval_incident_memory_phase34 import (
    ARMS,
    CONTEXT_BUDGET,
    PRIVATE,
    ROOT,
    cases,
    make_plan,
    private_write,
    source_fingerprints,
)
from langgraph_sdk import get_client

PORTS = {"A": 18047, "B": 18048, "C": 18049, "D": 18050}
SECRET_PATTERN = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+)", re.IGNORECASE)


def env(arm: str) -> dict[str, str]:
    values = dict(line.split("=", 1) for line in (PRIVATE / f"env-{arm}").read_text().splitlines()
                  if "=" in line)
    if int(values["CONTEXT_ESTIMATED_TOTAL_BUDGET"]) != CONTEXT_BUDGET:
        raise ValueError("运行预算与冻结计划不一致")
    return values


def client(arm: str):
    return get_client(url=f"http://127.0.0.1:{PORTS[arm]}", api_key=env(arm)["DEMO_API_TOKEN"])


def map_thread(thread: str, spec: dict) -> None:
    path = PRIVATE / "thread-map.json"
    mapping = json.loads(path.read_text())
    if thread in mapping:
        raise ValueError("Thread ID 重复")
    mapping[thread] = spec
    private_write(path, mapping)


async def stream(client_, thread: str, *, text: str | None = None,
                 resume: dict | None = None) -> dict:
    output = {"end": None, "interrupt": None, "state": None, "error": None}
    async for event in client_.runs.stream(
            thread, "agent", input={"messages": [{"type": "human", "content": text}]}
            if text is not None else None,
            command={"resume": resume} if resume is not None else None,
            stream_mode=["values", "updates"], stream_resumable=True):
        if event.event == "values" and isinstance(event.data, dict):
            output["state"] = event.data
        elif event.event == "updates" and isinstance(event.data, dict):
            interrupts = event.data.get("__interrupt__") or []
            if interrupts:
                output["interrupt"] = interrupts[0]["value"]
        elif event.event == "end":
            output["end"] = event.data.get("status") if isinstance(event.data, dict) else event.data
        elif event.event == "error":
            output["error"] = "aegra_error_event"
    return output


def safe_state(state: dict, secrets: list[str]) -> dict:
    messages = []
    for message in state.get("messages") or []:
        item = {key: message.get(key) for key in
                ("type", "name", "id", "content", "status", "tool_call_id", "tool_calls",
                 "usage_metadata", "response_metadata") if key in message}
        raw = json.dumps(item, ensure_ascii=False)
        if any(value and value in raw for value in secrets) or SECRET_PATTERN.search(raw):
            raise RuntimeError("secret_exposure_detected")
        messages.append(item)
    return {"messages": messages,
            "memory_retrieval_status": state.get("memory_retrieval_status"),
            "memory_references": state.get("memory_references") or [],
            "reader_attestations_count": len(state.get("reader_attestations") or []),
            "context_summary_status": (state.get("context_summary") or {}).get("status")}


def check_structure(messages: list[dict]) -> None:
    pending = set()
    for message in messages:
        if message.get("type") == "ai":
            for call in message.get("tool_calls") or []:
                ident = call.get("id")
                if not ident or ident in pending:
                    raise ValueError("bad_tool_call_id")
                pending.add(ident)
        elif message.get("type") == "tool":
            ident = message.get("tool_call_id")
            if ident not in pending:
                raise ValueError("unpaired_tool_message")
            pending.remove(ident)
    if pending:
        raise ValueError("missing_tool_message")


async def prepare_memory(arm: str) -> None:
    api = client(arm)
    manifest = PRIVATE / f"memory-seed-{arm}.json"
    records = json.loads(manifest.read_text())["records"] if manifest.exists() else []
    completed = {(item["case_id"], item["index"]) for item in records}
    for case in cases():
        for index, _seed in enumerate(case["memory_seeds"]):
            if (case["case_id"], index) in completed:
                continue
            thread = (await api.threads.create())["thread_id"]
            map_thread(thread, {"kind": "memory", "case_id": case["case_id"], "index": index})
            diagnosis = await stream(api, thread, text=case["user_prompt"])
            if diagnosis["end"] != "success":
                raise RuntimeError("Memory 种子诊断失败")
            review_run = await stream(api, thread, text="/remember-incident")
            review = review_run["interrupt"]
            if not review or review.get("kind") != "incident_memory_review":
                raise RuntimeError("Memory 种子审阅中断缺失")
            resume = {"kind": review["kind"], "candidate_id": review["candidate_id"],
                      "candidate_hash": review["candidate_hash"],
                      "schema_version": review["schema_version"], "decision": "approve"}
            saved = await stream(api, thread, resume=resume)
            state = (await api.threads.get_state(thread))["values"]
            if saved["end"] != "success" or state.get("memory_status") != "stored":
                raise RuntimeError("Memory 脚本审批保存失败")
            from kube_triage.incident_memory import validate_record
            record = state["memory_record"]
            validate_record(record, "demo-user", thread)
            records.append({"case_id": case["case_id"], "index": index,
                            "memory_id": record["memory_id"], "approval": "scripted_demo_approval"})
            private_write(manifest, {"records": records,
                                     "approval_kind": "scripted_demo_approval"})
            print(json.dumps({"arm": arm, "case_id": case["case_id"],
                              "index": index, "seeded": True}), flush=True)


async def prepare_history(arm: str, phase: str) -> None:
    api = client(arm)
    plan = make_plan(phase)
    by_case = {row["case_id"]: row for row in cases()}
    path = PRIVATE / f"history-{phase}-{arm}.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    for pair in plan["pairs"]:
        pair_id = pair["pair_id"]
        if pair_id in done:
            continue
        case = by_case[pair["case_id"]]
        thread = (await api.threads.create())["thread_id"]
        map_thread(thread, {"kind": "history", "case_id": case["case_id"],
                            "pair_id": pair_id, "arm": arm})
        for _index in range(case["historical_conversation"]["rounds"]):
            result = await stream(api, thread, text=case["user_prompt"])
            if result["end"] != "success":
                raise RuntimeError("旧对话正式 Graph 前置流程失败")
        state = (await api.threads.get_state(thread))["values"]
        messages = state.get("messages") or []
        if len(messages) != case["historical_conversation"]["rounds"] * 4:
            raise RuntimeError("旧对话轮次结构不完整")
        text_fingerprint = hashlib.sha256(json.dumps([
            {"type": item.get("type"), "name": item.get("name"),
             "content": item.get("content") if item.get("type") != "tool" else "synthetic_tool"}
            for item in messages], ensure_ascii=False).encode()).hexdigest()
        done[pair_id] = {"thread_id": thread, "rounds": case["historical_conversation"]["rounds"],
                         "message_count": len(messages), "structure_fingerprint": text_fingerprint}
        private_write(path, done)
        print(json.dumps({"arm": arm, "pair_id": pair_id,
                          "history_rounds": done[pair_id]["rounds"]}), flush=True)


async def execute_one(arm: str, phase: str, pair: dict, case: dict) -> dict:
    run_id = f"{phase}-{pair['pair_id']}-{arm}"
    history = json.loads((PRIVATE / f"history-{phase}-{arm}.json").read_text())
    thread = history[pair["pair_id"]]["thread_id"]
    secrets = [env(arm)[key] for key in ("LLM_API_KEY", "DEMO_API_TOKEN",
                                         "INCIDENT_MEMORY_PROVENANCE_SECRET", "POSTGRES_PASSWORD")]
    started = time.monotonic()
    output = {"run_id": run_id, "pair_id": pair["pair_id"], "case_id": case["case_id"],
              "arm": arm, "thread_id": thread, "status": "failed", "error_code": None,
              "source_fingerprints": source_fingerprints()}
    try:
        result = await stream(client(arm), thread, text=case["user_prompt"])
        if result["error"]:
            raise RuntimeError(result["error"])
        state = (await client(arm).threads.get_state(thread))["values"]
        safe = safe_state(state, secrets)
        check_structure(safe["messages"])
        current = safe["messages"][history[pair["pair_id"]]["message_count"]:]
        calls = [call for item in current if item.get("type") == "ai"
                 for call in item.get("tool_calls") or []]
        tools = [item for item in current if item.get("type") == "tool"]
        answer = next((str(item.get("content", "")) for item in reversed(current)
                       if item.get("type") == "ai" and not item.get("tool_calls")), "")
        target_proof = False
        wrong_target_success = False
        for item in tools:
            if item.get("name") != "pods_get" or item.get("status") != "success":
                continue
            envelope = json.loads(item.get("content") or "{}")
            pod = json.loads(envelope.get("result") or "{}") if envelope.get("ok") else {}
            meta = pod.get("metadata") or {}
            if meta.get("name") == case["target_pod"] and meta.get("namespace") == case["namespace"]:
                target_proof = True
            else:
                wrong_target_success = True
        model_ids = sorted({(item.get("response_metadata") or {}).get("model_name")
                            for item in current if item.get("name") == "triage_llm"
                            and (item.get("response_metadata") or {}).get("model_name")})
        output.update({"status": "completed" if result["end"] == "success" and answer else "failed",
                       "error_code": None if result["end"] == "success" and answer else "missing_answer",
                       "end_status": result["end"], "answer": answer,
                       "tool_calls": calls, "tool_count": len(calls),
                       "target_proof": target_proof, "wrong_target_success": wrong_target_success,
                       "tool_failures": sum(item.get("status") != "success" for item in tools),
                       "llm_decisions": sum(item.get("name") == "triage_llm" for item in current),
                       "model_ids": model_ids,
                       "usage": {key: sum((item.get("usage_metadata") or {}).get(key, 0)
                                          for item in current if item.get("name") == "triage_llm")
                                 for key in ("input_tokens", "output_tokens")},
                       "memory_retrieval_status": safe["memory_retrieval_status"],
                       "memory_hits": len(safe["memory_references"]),
                       "memory_reference_displayed": "历史案例参考（非当前证据）" in answer,
                       "context_summary_status": safe["context_summary_status"],
                       "reader_attestations_count": safe["reader_attestations_count"]})
        private_write(PRIVATE / phase / "traces" / f"{run_id}.json",
                      {"run_id": run_id, "current_messages": current,
                       "memory_references": safe["memory_references"],
                       "end_status": result["end"]})
    except Exception as exc:
        output["error_code"] = ("secret_exposure_detected" if "secret_exposure_detected" in str(exc)
                                else type(exc).__name__)
        if output["error_code"] == "secret_exposure_detected":
            raise
    output["latency_ms"] = round((time.monotonic() - started) * 1000)
    return output


async def run_phase(phase: str, case_only: str | None, concurrency: int,
                    max_pairs: int | None) -> None:
    plan = make_plan(phase)
    stored = PRIVATE / f"plan-{phase}.json"
    if not stored.exists() or json.loads(stored.read_text()) != plan:
        raise RuntimeError("正式运行前必须冻结相同计划与 Golden SHA")
    if phase in {"formal-v1", "formal-v2", "fault-v1", "fault-v2"}:
        freeze_path = PRIVATE / ("formal-v2-source-freeze.json" if phase in {
            "formal-v2", "fault-v2"} else "formal-source-freeze.json")
        if not freeze_path.exists():
            raise RuntimeError("正式代码 SHA 尚未冻结")
        frozen = json.loads(freeze_path.read_text())
        if any(frozen.get(key) != value for key, value in source_fingerprints().items()):
            raise RuntimeError("Graph、Mock Reader 或 Golden 运行中发生漂移")
    by_case = {row["case_id"]: row for row in cases()}
    path = PRIVATE / phase / "runs.json"
    current = {row["run_id"]: row for row in json.loads(path.read_text())} if path.exists() else {}
    selected = [pair for pair in plan["pairs"]
                if not case_only or pair["case_id"] == case_only]
    if max_pairs is not None:
        selected = selected[:max_pairs]
    semaphore = asyncio.Semaphore(concurrency)
    save_lock = asyncio.Lock()
    stop = asyncio.Event()

    async def one_pair(pair: dict) -> None:
        for arm in pair["arm_order"]:
            if stop.is_set():
                return
            run_id = f"{phase}-{pair['pair_id']}-{arm}"
            if run_id in current:
                continue
            async with semaphore:
                row = await execute_one(arm, phase, pair, by_case[pair["case_id"]])
            async with save_lock:
                current[run_id] = row
                private_write(path, sorted(current.values(), key=lambda item: item["run_id"]))
            print(json.dumps({"run_id": run_id, "status": row["status"],
                              "error_code": row["error_code"],
                              "target_proof": row.get("target_proof"),
                              "wrong_target_success": row.get("wrong_target_success")}), flush=True)
            answer = row.get("answer", "")
            definite_target_claim = (not row.get("target_proof") and
                                     any(term in answer for term in
                                         ("目标 Pod 已核验", "目标已核验", "当前已健康", "当前健康",
                                          "已确认根因", "根因是")) and
                                     not any(term in answer for term in
                                             ("未核验", "无法核验", "不能确认", "未确认")))
            if definite_target_claim or row["error_code"] in {
                    "secret_exposure_detected", "unpaired_tool_message"}:
                stop.set()
                raise RuntimeError("P0 Gate 触发：停止当前配置并保留证据")

    await asyncio.gather(*(one_pair(pair) for pair in selected))


async def run_p0() -> None:
    """正式对照前独立复现 P34-09，不计入 Pilot/正式分母。"""
    arm = "A"
    case = next(row for row in cases() if row["case_id"] == "P34-09")
    api = client(arm)
    thread = (await api.threads.create())["thread_id"]
    map_thread(thread, {"kind": "p0-probe", "case_id": case["case_id"], "arm": arm})
    result = await stream(api, thread, text=case["user_prompt"])
    state = (await api.threads.get_state(thread))["values"]
    secrets = [env(arm)[key] for key in ("LLM_API_KEY", "DEMO_API_TOKEN",
                                         "INCIDENT_MEMORY_PROVENANCE_SECRET", "POSTGRES_PASSWORD")]
    safe = safe_state(state, secrets)
    check_structure(safe["messages"])
    answer = next((str(item.get("content", "")) for item in reversed(safe["messages"])
                   if item.get("type") == "ai" and not item.get("tool_calls")), "")
    tools = [item for item in safe["messages"] if item.get("type") == "tool"]
    output = {"batch": "p0-before-fix", "case_id": case["case_id"],
              "thread_id": thread, "end_status": result["end"], "answer": answer,
              "tools": tools, "source_graph_sha256": hashlib.sha256(
                  (ROOT / "server/src/kube_triage/graph.py").read_bytes()).hexdigest(),
              "real_model": True, "reader": "synthetic_mock_only"}
    path = PRIVATE / "p0-before-fix-v2.json"
    if path.exists():
        raise RuntimeError("P0 v2 轨迹已存在，拒绝覆盖")
    private_write(path, output)
    print(json.dumps({"case_id": case["case_id"], "end_status": result["end"],
                      "tool_count": len(tools), "answer": answer}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["memory", "history", "run", "p0"])
    parser.add_argument("--arm", choices=list(ARMS))
    parser.add_argument("--phase", choices=["pilot-v1", "pilot-v2", "pilot-v3",
                                            "formal-v1", "formal-v2", "fault-v1", "fault-v2"],
                        default="pilot-v3")
    parser.add_argument("--case-only")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-pairs", type=int)
    args = parser.parse_args()
    if args.command in {"memory", "history"} and not args.arm:
        parser.error("准备命令必须指定 --arm")
    if args.command == "memory":
        asyncio.run(prepare_memory(args.arm))
    elif args.command == "history":
        asyncio.run(prepare_history(args.arm, args.phase))
    elif args.command == "p0":
        asyncio.run(run_p0())
    else:
        if not 1 <= args.concurrency <= 4:
            parser.error("并发必须为 1..4")
        asyncio.run(run_phase(args.phase, args.case_only,
                              args.concurrency, args.max_pairs))


if __name__ == "__main__":
    main()
