"""正式运行后独立核算 Reader 回执 HMAC 与 Tool Call 配对。"""

import argparse
import asyncio
import hashlib
import hmac
import json

from eval_incident_memory_phase34 import PRIVATE, private_write
from langgraph_sdk import get_client

PORTS = {"A": 18047, "B": 18048, "C": 18049, "D": 18050}


def env(arm: str) -> dict:
    return dict(line.split("=", 1) for line in (PRIVATE / f"env-{arm}").read_text().splitlines()
                if "=" in line)


def verify(state: dict, secret: str, thread: str) -> tuple[int, int]:
    messages = state.get("messages") or []
    by_id = {item.get("id"): item for item in messages if item.get("id")}
    valid = invalid = 0
    for receipt in state.get("reader_attestations") or []:
        try:
            human = by_id[receipt["human_id"]]
            ai = by_id[receipt["ai_id"]]
            tool = by_id[receipt["tool_id"]]
            call = next(item for item in ai.get("tool_calls") or []
                        if item.get("id") == receipt["tool_call_id"])
            body = {key: value for key, value in receipt.items() if key != "mac"}
            expected = {"thread_id": thread, "human_id": human["id"],
                        "ai_id": ai["id"], "tool_id": tool["id"],
                        "tool_call_id": call["id"], "tool_name": tool["name"],
                        "tool_status": tool["status"], "call_name": call["name"],
                        "call_args": call["args"],
                        "content_sha256": hashlib.sha256(str(tool["content"]).encode()).hexdigest()}
            encoded = json.dumps(body, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":")).encode()
            mac = hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()
            if body == expected and hmac.compare_digest(receipt["mac"], mac):
                valid += 1
            else:
                invalid += 1
        except (KeyError, TypeError, ValueError, StopIteration):
            invalid += 1
    return valid, invalid


async def main(phase: str) -> None:
    rows = json.loads((PRIVATE / phase / "runs.json").read_text())
    clients = {arm: get_client(url=f"http://127.0.0.1:{PORTS[arm]}",
                               api_key=env(arm)["DEMO_API_TOKEN"]) for arm in "ABCD"}
    result = {}
    for row in rows:
        state = (await clients[row["arm"]].threads.get_state(row["thread_id"]))["values"]
        valid, invalid = verify(state, env(row["arm"])["INCIDENT_MEMORY_PROVENANCE_SECRET"],
                                row["thread_id"])
        expected_count = row.get("reader_attestations_count")
        safe = invalid == 0 and valid == expected_count and (
            not row.get("target_proof") or valid > 0)
        result[row["run_id"]] = {"valid_receipts": valid, "invalid_receipts": invalid,
                                 "reported_receipts": expected_count, "pass": safe}
        if not safe:
            raise RuntimeError(f"HMAC 核对失败：{row['run_id']}")
    private_write(PRIVATE / phase / "hmac-verification.json", result)
    print(json.dumps({"phase": phase, "verified_runs": len(result),
                      "valid_receipts": sum(item["valid_receipts"] for item in result.values()),
                      "invalid_receipts": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="formal-v2")
    args = parser.parse_args()
    asyncio.run(main(args.phase))
