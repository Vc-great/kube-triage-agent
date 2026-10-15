"""以正式 Remember Graph 的 SDK Resume 种下合成记录，标记 scripted_demo_approval。"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from kube_triage import incident_memory as memory
from langgraph_sdk import get_client

PRIVATE = Path(".local/phase33")
CASES = json.loads(Path("scripts/eval_incident_memory_cases/phase33-main-v1.json").read_text())["cases"]


def private_write(path: Path, value) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(value, file, ensure_ascii=False, sort_keys=True, indent=2)
        file.write("\n")


async def run(client, thread, *, text=None, resume=None):
    result = {"interrupt": None, "memory_status": None, "end": None}
    async for part in client.runs.stream(
            thread, "agent", input={"messages": [{"type": "human", "content": text}]}
            if text else None, command={"resume": resume} if resume else None,
            stream_mode=["updates", "values"], stream_resumable=True):
        if part.event == "updates" and isinstance(part.data, dict):
            interrupts = part.data.get("__interrupt__") or []
            if interrupts:
                result["interrupt"] = interrupts[0]["value"]
        if part.event == "values" and isinstance(part.data, dict):
            result["memory_status"] = part.data.get("memory_status")
        if part.event == "end":
            result["end"] = part.data.get("status") if isinstance(part.data, dict) else part.data
    return result


async def main(arm: str, port: int) -> None:
    env = dict(x.split("=", 1) for x in (PRIVATE / f"env-{arm}").read_text().splitlines()
               if "=" in x)
    client = get_client(url=f"http://127.0.0.1:{port}", api_key=env["DEMO_API_TOKEN"])
    map_path = PRIVATE / "thread-map.json"
    manifest_path = PRIVATE / f"scripted-seed-{arm}.json"
    records = json.loads(manifest_path.read_text())["records"] if manifest_path.exists() else []
    done = {(item["case_id"], item["index"]) for item in records}
    kind = "relevant" if arm == "B" else "distractor"
    for case in CASES:
        for index, _history in enumerate(case["historical_records"][kind]):
            if (case["case_id"], index) in done:
                continue
            thread = (await client.threads.create())["thread_id"]
            mapping = json.loads(map_path.read_text())
            mapping[thread] = {"case_id": case["case_id"], "arm": arm, "index": index}
            private_write(map_path, mapping)
            diagnosis = await run(client, thread, text=case["user_prompt"])
            if diagnosis["end"] != "success":
                raise RuntimeError("synthetic diagnosis failed")
            pending = await run(client, thread, text="/remember-incident")
            review = pending["interrupt"]
            if not review or review.get("kind") != "incident_memory_review":
                raise RuntimeError("synthetic review missing")
            saved = await run(client, thread, resume={
                "kind": review["kind"], "candidate_id": review["candidate_id"],
                "candidate_hash": review["candidate_hash"],
                "schema_version": review["schema_version"], "decision": "approve"})
            if saved["memory_status"] != "stored":
                raise RuntimeError(f"synthetic commit {saved['memory_status']}")
            state = (await client.threads.get_state(thread))["values"]
            record = state.get("memory_record")
            if not isinstance(record, dict):
                raise TypeError("missing synthetic record")
            memory.validate_record(record, "demo-user", thread)
            records.append({"case_id": case["case_id"], "index": index,
                            "memory_id": record["memory_id"], "record": record,
                            "approval": "scripted_demo_approval"})
            private_write(manifest_path, {"provenance": "scripted_demo_approval",
                                          "records": records})
            print(json.dumps({"arm": arm, "case_id": case["case_id"],
                              "index": index, "status": "stored"}), flush=True)
    print(json.dumps({"arm": arm, "records": len(records),
                      "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                      "provenance": "scripted_demo_approval"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("arm", choices=["B", "C"])
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.arm, args.port))
