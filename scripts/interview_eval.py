"""Local-only paired experiments for the three interview cases (Langfuse v4)."""

import argparse
import fcntl
import hashlib
import json
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import dev
import httpx
import langfuse_case1 as case1
import obs_lab as lab
import obs_lab_scores as rules
from obs_lab_score_upload import ScoreCloud, publish, same_score

from kube_triage.prompts import INTERVIEW_SUFFIX, SYSTEM_PROMPT

DATASET = "kube-triage-interview-v1"
DIRECTORY = lab.ROOT / ".local/observability-lab/interview-v1"
ARMS = {"baseline": "A", "candidate": "interview-candidate"}


class LocalAPI:
    read_score = ScoreCloud.read_score

    def __init__(self, credentials):
        self.base = dev.normalize_langfuse_url(credentials["LANGFUSE_BASE_URL"], local_only=True)
        self.client = httpx.Client(base_url=self.base + "/api/public/", trust_env=False,
                                  follow_redirects=False, timeout=15, auth=(
                                      credentials["LANGFUSE_PUBLIC_KEY"], credentials["LANGFUSE_SECRET_KEY"]))
        projects = self.request("projects")["data"]
        if len(projects) != 1 or (projects[0]["id"], projects[0]["name"]) != ("agent-lab", "Agent Lab"):
            raise ValueError("STOP: incorrect local project")

    def request(self, path, query=None, payload=None, optional=False):
        timeout = min(15, getattr(self, "deadline", time.monotonic() + 15) - time.monotonic())
        if timeout <= 0:
            raise ValueError("BLOCKED: local API deadline exceeded")
        response = self.client.request("GET" if payload is None else "POST", path,
                                       params=query, json=payload,
                                       timeout=timeout)
        if optional and response.status_code == 404:
            return None
        if not response.is_success:
            raise ValueError(f"STOP: local Langfuse HTTP {response.status_code} on {path}")
        return response.json()


def frozen_items():
    rules.frozen_cases()
    spec = json.loads((lab.ROOT / "eval/interview/v1.json").read_text())
    if set(spec) != set(case1.SCENARIOS):
        raise ValueError("STOP: expected three scenarios")
    result = {}
    for scenario, expected in spec.items():
        fixture = lab.ROOT / "server/src/kube_triage/fixtures/issue12" / (lab.CASES[scenario] + ".json")
        result[scenario] = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, DATASET + "/" + scenario)),
            "datasetName": DATASET, "input": lab.scenario_question(scenario),
            "expectedOutput": expected, "status": "ACTIVE",
            "metadata": {"scenario": scenario, "fixture": fixture.stem,
                         "fixture_sha256": rules.sha256(fixture), "rules": rules.VERSION,
                         "rule_sha256": rules.sha256(Path(rules.__file__))}}
    return result


def sync(api, create=False):
    items = frozen_items()
    metadata = {"sha256": rules.digest(items)}
    path = "v2/datasets/" + DATASET
    dataset = api.request(path, optional=True)
    if dataset is None and create:
        api.request("v2/datasets", payload={"name": DATASET, "metadata": metadata})
        dataset = api.request(path)
    if not dataset or dataset["metadata"] != metadata or dataset["projectId"] != "agent-lab":
        raise ValueError("STOP: dataset missing or version conflict")
    remote = {}
    for scenario, item in items.items():
        path = "dataset-items/" + item["id"]
        row = api.request(path, optional=True)
        if row is None and create:
            api.request("dataset-items", payload=item)
            row = api.request(path)
        if not row or row["datasetId"] != dataset["id"] or any(row.get(k) != v for k, v in item.items()):
            raise ValueError("STOP: dataset item missing or version conflict")
        remote[scenario] = row
    listed = api.request("dataset-items", {"datasetName": DATASET, "limit": 100})
    if {r["id"] for r in listed["data"]} != {r["id"] for r in remote.values()} or (
            listed["meta"]["totalItems"] != 3):
        raise ValueError("STOP: dataset membership conflict")
    return dataset, remote


def context(activity, arm, item, revision):
    name = activity + "-" + arm
    prompt = SYSTEM_PROMPT + (INTERVIEW_SUFFIX if arm == "candidate" else "")
    attrs = {"langfuse.experiment.id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)),
             "langfuse.experiment.name": name, "langfuse.experiment.dataset.id": item["datasetId"],
             "langfuse.experiment.item.id": item["id"],
             "langfuse.experiment.metadata.prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
             "langfuse.experiment.metadata.revision": revision}
    if item.get("version"):
        attrs["langfuse.experiment.item.version"] = item["version"]
    return {"question": item["input"], "expected": item["expectedOutput"], "attributes": attrs}


def match_item(api, request, row):
    attrs = request["attributes"]
    query = {"experimentId": attrs["langfuse.experiment.id"],
             "experimentItemId": attrs["langfuse.experiment.item.id"],
             "fromStartTime": (datetime.fromisoformat(row["start"])-timedelta(seconds=5)).isoformat(),
             "fields": "core,dataset,io,experimentMetadata", "limit": 2}
    result = api.request("experiment-items", query)
    records = result["data"]
    if not records:
        return False
    if len(records) != 1 or result.get("meta", {}).get("cursor"):
        raise ValueError("STOP: duplicate experiment item")
    record = records[0]
    expected = {"experimentId": query["experimentId"], "experimentItemId": query["experimentItemId"],
                "experimentDatasetId": attrs["langfuse.experiment.dataset.id"],
                "experimentName": attrs["langfuse.experiment.name"], "traceId": row["cloud"]["trace_id"],
                "id": row["cloud"]["root_id"]}
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError("STOP: experiment identity mismatch")
    for key, value in (("input", request["question"]), ("output", row["final_answer"]),
                       ("expectedOutput", request["expected"])):
        actual = record.get(key)
        if isinstance(actual, str) and actual != value:
            try:
                actual = json.loads(actual)
            except ValueError:
                pass
        if actual != value:
            raise ValueError(f"STOP: experiment {key} mismatch")
    return True


def score(path, entry, row, observations):
    raw = case1.read_json(path / "raw" / entry["key"] / "private.json")
    scenario = entry["scenario_id"]
    result = rules.score_run(row, raw, rules.frozen_cases()[rules.TARGETS[scenario]])
    inspected = lab.inspect_run(raw["state"], raw["runs"], raw["events"])
    if (inspected["run_id"] != row["run_id"] or raw["thread_id"] != row["thread_id"]
            or not row.get("history_final_answer_valid")):
        raise ValueError("STOP: saved execution identity or final answer missing")
    if not row["reader_evidence"]["tool_selection_compliant"]:
        raise ValueError("STOP: unsafe tool call")
    if set(row["models_observed"]) != {"gpt-6-luna"}:
        raise ValueError("STOP: unexpected observed model")
    expected_prompt = SYSTEM_PROMPT + (INTERVIEW_SUFFIX if entry["arm"] == "candidate" else "")
    generations = [o for o in observations if o["type"] == "GENERATION"]
    if len(generations) != row["model_decisions"]:
        raise ValueError("STOP: missing observed generation inputs")
    for generation in generations:
        messages = json.loads(generation["input"])["messages"][0]
        system = [m["kwargs"]["content"] for m in messages if m["kwargs"].get("type") == "system"]
        if system != [expected_prompt]:
            raise ValueError("STOP: actual generation prompt differs")
    return {**result, "arm": entry["arm"], "scenario_id": scenario, "batch_id": path.name,
            "run_id": row["run_id"], "thread_id": row["thread_id"], "trace_id": row["cloud"]["trace_id"],
            "source_sha256": rules.digest(case1.read_json(path / "raw" / entry["key"] / "hashes.json")),
            "score_timestamp": row["end"], "project_id": "agent-lab"}


def run(args, api, path):
    _, items = sync(api)
    manifest = path / "activity.json"
    if args.command == "verify":
        state = case1.read_json(manifest)
        identity = state["identity"]
        cloud, _ = case1.target(args.env_file)
    else:
        values, credentials, cloud, _ = case1.preflight(args.env_file)
        if values["LLM_MODEL"] != "gpt-6-luna":
            raise ValueError("STOP: unapproved model")
        provenance = case1.source_provenance()
        identity = {"revision": provenance["git_head"], "dataset": rules.digest(frozen_items()),
                    "model": values["LLM_MODEL"], "files": provenance["file_sha256"]}
        state = case1.read_json(manifest) if manifest.exists() else {
            "activity_id": path.name, "identity": identity, "runs": []}
    if state["identity"] != identity or identity["dataset"] != rules.digest(frozen_items()):
        raise ValueError("STOP: experiment configuration changed")
    runs = []
    for scenario in case1.SCENARIOS:
        for arm, variant in ARMS.items():
            entry = {"key": scenario + "-" + arm, "scenario_id": scenario, "arm": arm}
            request = context(path.name, arm, items[scenario], identity["revision"])
            observations = None
            if entry in state["runs"]:
                row = case1.load_row(path, entry)
                if case1.infrastructure_valid(row):
                    observations = case1.refresh(cloud, row)
            elif args.command == "run":
                existing = api.request("experiment-items", {
                    "experimentId": request["attributes"]["langfuse.experiment.id"],
                    "experimentItemId": items[scenario]["id"], "limit": 1,
                    "fromStartTime": items[scenario]["createdAt"]})
                if existing["data"]:
                    raise ValueError("STOP: item already executed; locate its original manifest")
                state["runs"].append(entry)
                case1.save(manifest, state)
                row = case1.execute_one(path, state, entry, {
                    **values, "EVAL_PROMPT_VARIANT": variant,
                    "INTERVIEW_EXPERIMENT": json.dumps(request, ensure_ascii=False)
                }, credentials, cloud, 120)
            else:
                continue
            if not case1.infrastructure_valid(row) or not row.get("case1_trace_ready"):
                raise ValueError("BLOCKED: incomplete Run or Trace; reserved slot retained")
            if observations is None:
                observations = case1.read_json(path / "raw" / entry["key"] / "observations.json")
            scored = score(path, entry, row, observations)
            for field in ("trace_id", "run_id", "thread_id"):
                if any(seen[field] == scored[field] for seen in runs):
                    raise ValueError("STOP: duplicate " + field)
            for attempt in range(12):
                if match_item(api, request, row):
                    break
                if attempt == 11:
                    raise ValueError("BLOCKED: experiment ingestion pending")
                time.sleep(5)
            runs.append(scored)
            print(entry["key"], "verified", scored["trace_id"], flush=True)
    if len(runs) != len(case1.SCENARIOS) * len(ARMS):
        raise ValueError("BLOCKED: paired experiment incomplete")
    report = {"schema": rules.VERSION, "runs": runs}
    plan = rules.upload_plan(report)
    report["upload_plan"] = plan
    case1.save(path / "report.json", report)
    for arm in ARMS:
        for name in runs[0]["rules"]:
            counts = Counter(r["rules"][name]["status"] if r["rules"][name]["applicable"] else "N/A"
                             for r in runs if r["arm"] == arm)
            print(arm, name, dict(counts))
    print("Score plan:", plan["plan_sha256"], plan["max_writes"])


def matches_local_score(actual, expected):
    # Langfuse 4.72 stores DateTime64(3); match the exact UTC millisecond and all content.
    timestamp = datetime.fromisoformat(expected["timestamp"]).isoformat(timespec="milliseconds")
    return actual.get("projectId") == "agent-lab" and same_score(actual, {**expected, "timestamp": timestamp})


def verify_scores(api, path, plan):
    journal = case1.read_json(path / "score-journal.json")
    if journal["plan_sha256"] != plan["plan_sha256"] or len(plan["scores"]) != 30:
        raise ValueError("STOP: score journal mismatch")
    for score in plan["scores"]:
        actual = api.read_score(score)
        if actual is None or not matches_local_score(actual, score):
            raise ValueError("BLOCKED: local Score missing or different")
    return {"status": "PASS", "verified": len(plan["scores"]), "source": "local Scores API v3",
            "plan_sha256": plan["plan_sha256"], "checked_at": lab.utc()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "run", "verify", "scores", "verify-scores"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args()
    api = LocalAPI(dev.read_langfuse_env(args.env_file))
    path = DIRECTORY / "interview-ab-v1"
    case1.private_dir(path)
    with open(path / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "sync":
            dataset, items = sync(api, create=True)
            print("Verified dataset:", dataset["id"], *items)
        elif args.command in ("scores", "verify-scores"):
            report = case1.read_json(path / "report.json")
            if args.command == "scores":
                publish(report, args.approved_plan_sha256, 30, api, path / "score-journal.json",
                        matches=matches_local_score)
            outcome = verify_scores(api, path, rules.upload_plan(report))
            case1.save(path / "score-readback.json", outcome)
            print("Verified scores:", outcome["verified"])
        else:
            run(args, api, path)


if __name__ == "__main__":
    main()
