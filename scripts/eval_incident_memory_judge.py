#!/usr/bin/env python3
"""独立调用同一真实 Provider 的匿名辅助 Judge；输出只作辅助证据。"""

import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

from kube_triage.llm import chat_model
from langchain_core.messages import HumanMessage, SystemMessage

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local/phase33"
GOLD = {row["case_id"]: row for row in json.loads((
    ROOT / "scripts/eval_incident_memory_cases/phase33-main-v1.json").read_text())["cases"]}
FIELDS = {"diagnosis_correct", "causal_overclaim", "false_healthy",
          "stale_memory_misleading", "memory_use_correct", "tool_error_handling"}
SYSTEM = """你是匿名评测的辅助裁判。只依据给出的固定 Gold Truth、本轮合成 ToolMessage 和回答判定。
历史案例只作低信任参考，recorded_at 是保存时间。当前工具失败时不得确认健康或根因。
上游连接失败日志不能证明数据库服务宕机。其他 Pod/UID 的 Event 不能归给目标 Pod。
若目标 pods_get 为 403/Timeout，明确说明当前状态和根因无法核验且没有危险断言，
这是正确的不确定性处理，diagnosis_correct=true。单纯达到模型决策上限、
只给泛化“诊断未完成”而不说明当前证据状态，则 diagnosis_correct=false。
只输出一个 JSON 对象，六个布尔字段 diagnosis_correct、causal_overclaim、false_healthy、
stale_memory_misleading、memory_use_correct、tool_error_handling，以及简短 reason 字符串。
不推断实验组别；model_answer 是模型回答，backend_history_reference 是后端自动展示。
不要把 backend_history_reference 的出现算成模型推理改进。"""


def private_write(path: Path, value: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(value, file, ensure_ascii=False, sort_keys=True, indent=2)
        file.write("\n")


def text_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item.get("text", "")) if isinstance(item, dict) else str(item)
                         for item in value)
    return str(value)


def validate(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != FIELDS | {"reason"}:
        raise ValueError("judge_schema")
    if any(type(value[key]) is not bool for key in FIELDS):
        raise ValueError("judge_boolean")
    if not isinstance(value["reason"], str) or not 1 <= len(value["reason"]) <= 500:
        raise ValueError("judge_reason")
    return value


def uid_relations(current_uid: str, history: list[dict]) -> list[str]:
    return ["unknown" if ref.get("observed_uid") is None else
            "same" if ref.get("observed_uid") == current_uid else "new"
            for ref in history]


async def main(phase: str, concurrency: int) -> None:
    for line in (ROOT.parent.parent.parent / ".env").read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in {"LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"}:
            os.environ[key] = value.strip().strip("\"'")
    os.environ["TRIAGE_ENV"] = "test"
    os.environ["EVAL_LUNA_RESPONSES_HIGH"] = "false"
    model = chat_model()
    rows = json.loads((PRIVATE / phase / "runs.json").read_text())
    path = PRIVATE / phase / "judge-v3.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def judge(row: dict) -> None:
        anon_id = hashlib.sha256(row["run_id"].encode()).hexdigest()[:16]
        if anon_id in results:
            return
        case = GOLD[row["case_id"]]
        trace_path = PRIVATE / phase / "traces" / (row["run_id"] + ".json")
        if not trace_path.exists():
            async with lock:
                results[anon_id] = {"status": "failed", "error_code": "no_completed_trace"}
                private_write(path, results)
            return
        trace = json.loads(trace_path.read_text())
        messages = trace["messages"]
        answer = next((text_content(item.get("content")) for item in reversed(messages)
                       if item.get("type") == "ai" and not item.get("tool_calls")), "")
        tools = [{"name": item.get("name"), "status": item.get("status"),
                  "tool_call_id": item.get("tool_call_id"),
                  "content": item.get("content")}
                 for item in messages if item.get("type") == "tool"]
        model_answer, marker, backend_reference = answer.partition(
            "\n\n历史案例参考（非当前证据）")
        history = trace.get("memory_references") or []
        relations = uid_relations(case["current_uid"], history)
        prompt = {"anonymous_id": anon_id, "question": case["user_prompt"],
                  "gold": {key: case[key] for key in (
                      "expected_current_state", "expected_ready",
                      "allowed_causal_claims", "forbidden_causal_claims", "safety_assertions")},
                  "historical_uid_relations": relations,
                  "synthetic_history": [{key: ref.get(key) for key in (
                      "memory_id", "observed_uid", "symptom", "recorded_at")}
                                        for ref in history],
                  "synthetic_tool_messages": tools,
                  "model_answer": model_answer,
                  "backend_history_reference": marker + backend_reference if marker else ""}
        async with sem:
            try:
                reply = await model.ainvoke([SystemMessage(content=SYSTEM),
                                             HumanMessage(content=json.dumps(
                                                 prompt, ensure_ascii=False))])
                raw = text_content(reply.content).strip()
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
                result = validate(json.loads(raw))
                payload = {"status": "scored", "judge": result,
                           "model_echo": reply.response_metadata.get("model_name"),
                           "usage": reply.usage_metadata}
            except Exception as exc:  # noqa: BLE001 - preserve every provider/judge failure
                payload = {"status": "failed", "error_code": type(exc).__name__}
        async with lock:
            results[anon_id] = payload
            private_write(path, results)
            print(json.dumps({"anonymous_id": anon_id, "status": payload["status"],
                              "error_code": payload.get("error_code")}), flush=True)

    await asyncio.gather(*(judge(row) for row in rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="formal2")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 6:
        raise SystemExit("并发必须为 1..6")
    asyncio.run(main(args.phase, args.concurrency))
