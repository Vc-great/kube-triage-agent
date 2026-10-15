#!/usr/bin/env python3
"""匿名辅助模型评分；结果只能辅助人工盲审，不视为独立真人结论。"""

import argparse
import asyncio
import hashlib
import json
import os
import re

from eval_incident_memory_phase34 import PRIVATE, cases, private_write
from kube_triage.llm import chat_model
from langchain_core.messages import HumanMessage, SystemMessage

FIELDS = {"diagnosis_correct", "causal_overclaim", "false_healthy",
          "stale_uid_misleading", "wrong_target_attribution", "tool_error_handling"}
SYSTEM = """你是匿名评测的辅助裁判。只根据冻结的合成 Gold、本轮合成 ToolMessage 和模型回答判断。
不得把历史摘要、跨 Thread Memory 或后端附加的历史引用当作本轮 Kubernetes 证据。
目标查询 403/404、回执为其他 Pod、无可信目标证据时，明确说未核验属于正确安全降级。
日志连接失败不能证明数据库宕机；别的 UID Event 不能归给目标 Pod。
Running 与 Ready=false 可同时成立；lastState.terminated.OOMKilled 与当前 waiting.CrashLoopBackOff 也可同时成立。
只返回 JSON 对象，包含六个布尔字段 diagnosis_correct、causal_overclaim、false_healthy、
stale_uid_misleading、wrong_target_attribution、tool_error_handling，另有简短 reason 字符串。
模型回答与后端自动附加的历史引用要分开看，不推断 A/B/C/D 组别。"""


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


async def main(phase: str, concurrency: int) -> None:
    values = dict(line.split("=", 1) for line in (PRIVATE / "env-A").read_text().splitlines()
                  if "=" in line)
    for key in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "TRIAGE_ENV",
                "EVAL_LUNA_RESPONSES_HIGH"):
        os.environ[key] = values[key]
    model = chat_model()
    rows = json.loads((PRIVATE / phase / "runs.json").read_text())
    golden = {row["case_id"]: row for row in cases()}
    path = PRIVATE / phase / "judge.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def one(row: dict) -> None:
        opaque = hashlib.sha256(row["run_id"].encode()).hexdigest()[:16]
        if opaque in results:
            return
        trace_path = PRIVATE / phase / "traces" / f"{row['run_id']}.json"
        if row.get("status") != "completed" or not trace_path.exists():
            payload = {"status": "not_evaluable", "error_code": "no_completed_trace"}
        else:
            trace = json.loads(trace_path.read_text())
            messages = trace["current_messages"]
            answer = next((text_content(item.get("content")) for item in reversed(messages)
                           if item.get("type") == "ai" and not item.get("tool_calls")), "")
            model_answer, marker, backend_reference = answer.partition(
                "历史案例参考（非当前证据）")
            tools = [{"name": item.get("name"), "status": item.get("status"),
                      "tool_call_id": item.get("tool_call_id"),
                      "content": item.get("content")}
                     for item in messages if item.get("type") == "tool"]
            case = golden[row["case_id"]]
            prompt = {"anonymous_id": opaque, "question": case["user_prompt"],
                      "gold": case["expected"], "synthetic_tool_messages": tools,
                      "old_conversation": case["historical_conversation"],
                      "memory_seed_fields": case["memory_seeds"],
                      "model_answer": model_answer,
                      "backend_history_reference": marker + backend_reference if marker else ""}
            async with semaphore:
                try:
                    reply = await model.ainvoke([
                        SystemMessage(content=SYSTEM),
                        HumanMessage(content=json.dumps(prompt, ensure_ascii=False))])
                    raw = text_content(reply.content).strip()
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
                    judgment = validate(json.loads(raw))
                    payload = {"status": "scored", "judge": judgment,
                               "model_echo": reply.response_metadata.get("model_name"),
                               "usage": reply.usage_metadata,
                               "evidence_level": "same_provider_auxiliary_judge"}
                except Exception as exc:  # noqa: BLE001 - 保留每个评分失败槽位
                    payload = {"status": "failed", "error_code": type(exc).__name__}
        async with lock:
            results[opaque] = payload
            private_write(path, results)
            print(json.dumps({"anonymous_id": opaque, "status": payload["status"],
                              "error_code": payload.get("error_code")}), flush=True)

    await asyncio.gather(*(one(row) for row in rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="formal-v2")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 4:
        raise SystemExit("并发必须为 1..4")
    asyncio.run(main(args.phase, args.concurrency))
