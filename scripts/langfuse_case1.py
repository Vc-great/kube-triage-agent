"""Local case 1: bounded real Runs; immutable evidence; read-only report rebuilding."""

import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import dev
import obs_lab as lab
from case1_report import render_report
from obs_lab_verify import content_digest, verify_cloud

SCENARIOS = ("S01", "S05", "S06")
DIRECTORY = lab.ROOT / ".local/observability-lab/case1"
IMAGES = ("pgvector/pgvector:0.8.7-pg18-bookworm", "redis:8.4.7-alpine")


def read_json(path):
    if path.is_symlink():
        raise RuntimeError("CASE1_SYMLINK_DENIED")
    return json.loads(path.read_text())


def save(path, value, *, exclusive=False):
    """Atomic, private state; exclusive artifacts are never replaced."""
    if path.is_symlink():
        raise RuntimeError("CASE1_SYMLINK_DENIED")
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    target = path if exclusive else path.with_name(path.name + "." + secrets.token_hex(6))
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    if not exclusive:
        os.replace(target, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def private_dir(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RuntimeError("CASE1_SYMLINK_DENIED")
    lab.private_directory(path)


@contextmanager
def lock():
    private_dir(DIRECTORY)
    fd = os.open(DIRECTORY / "activity.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("CASE1_BUSY：另一个案例命令正在运行") from None
        yield
    finally:
        os.close(fd)


def target(env_file):
    """Configuration checks and GET only; no processes, model or score writes."""
    credentials = dev.read_langfuse_env(env_file)
    origin = dev.normalize_langfuse_url(credentials["LANGFUSE_BASE_URL"], local_only=True)
    cloud = lab.Cloud(credentials)
    projects = cloud.get("projects").get("data", [])
    if len(projects) != 1 or projects[0].get("id") != "agent-lab" or projects[0].get("name") != "Agent Lab":
        raise RuntimeError("CASE1_PROJECT_MISMATCH：必须是唯一的本地 Agent Lab 项目")
    return cloud, origin


def preflight(env_file):
    cloud, origin = target(env_file)
    values, credentials = lab.configuration(env_file)
    for path in (lab.ROOT / ".env", lab.ROOT / "server/.env", lab.ROOT / "server/.env.local"):
        if path.exists() and path != env_file:
            raise RuntimeError("CASE1_EXTRA_DOTENV：隔离目录存在第二配置源")
    if dev.occupied(8000):
        raise RuntimeError("CASE1_PORT_BUSY：8000 已占用，不操作既有服务")
    for image in IMAGES:
        result = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                                env=dev.safe_host_env(), capture_output=True, timeout=20, check=False)
        if result.returncode:
            raise RuntimeError("CASE1_IMAGE_UNAVAILABLE：先检查 Host 缓存，不自动下载")
    return values, credentials, cloud, origin


def source_provenance():
    """Version identity only; never read dotenv or arbitrary untracked files."""
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=lab.ROOT,
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    files = [lab.ROOT / "server/uv.lock", *sorted((lab.ROOT / "scripts").glob("obs_lab*.py")),
             lab.ROOT / "scripts/langfuse_case1.py", lab.ROOT / "scripts/dev.py",
             *sorted((lab.ROOT / "server/src/kube_triage").rglob("*.py"))]
    return {"recorded_at": lab.utc(), "git_head": revision, "python": sys.version.split()[0],
            "aegra": importlib.metadata.version("aegra-api"),
            "file_sha256": {str(p.relative_to(lab.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in files if p.is_file() and not p.is_symlink()}}


def activity(batch=None, *, create=False, new=False):
    if batch:
        if not re.fullmatch(r"case1-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", batch):
            raise RuntimeError("CASE1_BATCH_INVALID")
        path = DIRECTORY / batch
        state = read_json(path / "activity.json")
        if state.get("activity_id") != batch:
            raise RuntimeError("CASE1_BATCH_MISMATCH")
        return path, state
    current = DIRECTORY / "current.json"
    if current.exists() and not new:
        return activity(read_json(current)["activity_id"])
    if not create:
        raise RuntimeError("CASE1_NO_ACTIVITY：尚无运行记录")
    identifier = "case1-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)
    path = DIRECTORY / identifier
    private_dir(path)
    state = {"activity_id": identifier, "created_at": lab.utc(), "max_runs": 6,
             "runs": [], "schema": "case1-v1", "provenance": source_provenance()}
    save(path / "activity.json", state, exclusive=True)
    save(current, {"activity_id": identifier})
    return path, state


def reserve(path, state, scenario):
    if scenario not in SCENARIOS or len(state["runs"]) >= 6:
        raise RuntimeError("CASE1_BUDGET_EXHAUSTED")
    count = sum(r["scenario_id"] == scenario for r in state["runs"])
    if count >= 2:
        raise RuntimeError("CASE1_SCENARIO_ALREADY_RUN：不重复已执行场景")
    key = f"{scenario}-{count + 1}"
    entry = {"key": key, "scenario_id": scenario, "repeat": count + 1,
             "reserved_at": lab.utc()}
    state["runs"].append(entry)
    save(path / "activity.json", state)
    return entry


def infrastructure_valid(row):
    return (row.get("protocol_status") == "success" and not row.get("sse_error")
            and bool(row.get("models_observed")) and 1 <= row.get("model_decisions", 0) <= 4
            and row.get("tool_count", 0) <= 6
            and not (row.get("reader_evidence") or {}).get("model_execution_failure")
            and not (row.get("exporter") or {}).get("failure_count")
            and row.get("lifecycle", {}).get("completed") is True
            and not row.get("execution_error"))


def read_review(path, row):
    files = sorted((path / "reviews").glob("*.json")) if (path / "reviews").exists() else []
    for file in reversed(files):
        reviews = read_json(file)
        review = reviews.get(row.get("run_id"))
        if review:
            if (review.get("source") != "agent_review" or review.get("status") not in {"PASS", "FAIL"}
                    or review.get("answer_sha256") != content_digest(row.get("final_answer"))
                    or not review.get("reason") or review.get("rubric_version") != "case1-v1"):
                raise RuntimeError("CASE1_REVIEW_INVALID：来源、依据或回答哈希不符")
            return review
    return {}


def evidence_hashes(raw):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(raw.iterdir()) if p.is_file() and not p.is_symlink()}


def load_row(path, entry):
    raw = path / "raw" / entry["key"]
    result = raw / "result.json"
    if not result.exists():
        return {**entry, "protocol_status": "UNKNOWN", "execution_error": "incomplete_reserved_run"}
    row = read_json(result)
    expected = read_json(raw / "hashes.json")
    if any(hashlib.sha256((raw / name).read_bytes()).hexdigest() != digest
           for name, digest in expected.items()):
        raise RuntimeError("CASE1_EVIDENCE_CHANGED")
    row["diagnosis_review"] = read_review(path, row)
    row["evidence_path"] = str(raw)
    return row


def fetch_observations(cloud, row):
    if not row.get("run_id") or not row.get("thread_id") or not row.get("end"):
        return []
    start = (datetime.fromisoformat(row["start"]) - timedelta(seconds=2)).isoformat()
    end = (datetime.fromisoformat(row["end"]) + timedelta(seconds=2)).isoformat()
    observations = cloud.observations(row, start, end)
    result = verify_cloud(observations, row, "agent-lab", base_url=cloud.base_url)
    if result["trace_verified"]:
        observations = cloud.observations(row, start, end, trace_id=result["trace_id"])
    return observations


def trace_ready(row):
    result = row.get("cloud") or {}
    if row["scenario_id"] == "S01":
        return bool(result.get("chain_verified"))
    if (row.get("fault_evidence") or {}).get("fault_observed") is False:
        # A non-trigger is a real outcome, never a successful fault reproduction.
        return bool(result.get("chain_verified"))
    # A review is intentionally separate from chain evidence. Never alter the old verdict.
    missing = [m for m in result.get("scenario_missing", []) if m != "diagnosis_behavior_review"]
    return (bool(result.get("trace_verified")) and result.get("native_trace_complete") == "PASS"
            and not missing)


def refresh(cloud, row):
    observations = fetch_observations(cloud, row)
    row["cloud"] = verify_cloud(observations, row, "agent-lab", base_url=cloud.base_url)
    row["case1_trace_ready"] = trace_ready(row)
    if row["scenario_id"] in {"S05", "S06"}:
        row["case1_fault_event"] = ("TRIGGERED" if (row.get("fault_evidence") or {}).get(
            "fault_observed") else "NOT_TRIGGERED")
    return observations


def assert_previous(path, state, scenario, cloud, *, resume=False):
    rows = [load_row(path, entry) for entry in state["runs"]]
    for row in rows:
        if not infrastructure_valid(row):
            raise RuntimeError("CASE1_PREVIOUS_EXECUTION_BLOCKED：保留失败，不自动补跑")
        refresh(cloud, row)
        if not row["case1_trace_ready"]:
            raise RuntimeError("CASE1_PREVIOUS_TRACE_PENDING：先只读重建报告")
        if not row["diagnosis_review"]:
            raise RuntimeError("CASE1_REVIEW_REQUIRED：先逐条审阅已有回复")
    for previous in SCENARIOS[:SCENARIOS.index(scenario)]:
        if sum(row["scenario_id"] == previous for row in rows) != 2:
            raise RuntimeError("CASE1_ORDER：必须先完成前序场景")
    count = sum(row["scenario_id"] == scenario for row in rows)
    if count == 2 or (count and not resume):
        raise RuntimeError("CASE1_SCENARIO_ALREADY_RUN：仅显式 --continue 可执行未用槽位")
    if any(SCENARIOS.index(row["scenario_id"]) > SCENARIOS.index(scenario) for row in rows):
        raise RuntimeError("CASE1_ORDER")
    return count


def execute_one(path, state, entry, values, credentials, cloud, wait):
    raw = path / "raw" / entry["key"]
    private_dir(raw)
    row = {**entry, "start": lab.utc(), "protocol_status": "unknown"}
    configured = dict(values)
    if entry["scenario_id"] != "S01":
        configured["OBS_LAB_SCENARIO"] = entry["scenario_id"]
    old_session = os.environ.get("AO_SESSION_ID")
    os.environ["AO_SESSION_ID"] = state["activity_id"]
    try:
        with lab.isolated(configured, credentials, raw) as (base, token):
            lab.execute(base, token, entry["scenario_id"], state["activity_id"], 150, row,
                        raw / "private.json")
    except Exception as error:  # noqa: BLE001 - preserve evidence without credential-bearing errors
        row["execution_error"] = type(error).__name__
    finally:
        if old_session is None:
            os.environ.pop("AO_SESSION_ID", None)
        else:
            os.environ["AO_SESSION_ID"] = old_session
        row["end"] = lab.utc()
        row["lifecycle"] = lab.lifecycle_result(raw)
        row["exporter"] = lab.export_failures(raw)
        row["model_requests"] = lab.model_request_summary(raw)
    observations = []
    deadline = time.monotonic() + wait
    cloud.deadline = deadline
    try:
        while time.monotonic() < deadline:
            observations = refresh(cloud, row)
            if row["case1_trace_ready"]:
                break
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    except Exception as error:  # noqa: BLE001 - preserve evidence without credential-bearing errors
        row["ingestion_error"] = type(error).__name__
    finally:
        cloud.deadline = None
    row["ingestion_state"] = "VERIFIED" if row.get("case1_trace_ready") else "PENDING_INGESTION"
    save(raw / "observations.json", observations, exclusive=True)
    save(raw / "result.json", row, exclusive=True)
    save(raw / "hashes.json", evidence_hashes(raw), exclusive=True)
    return row


def build_report(path, state, cloud):
    """GET existing observations only. No preflight, model, process, Run or Score creation."""
    if state.get("langfuse_base_url") != cloud.base_url:
        raise RuntimeError("CASE1_TARGET_CHANGED")
    cloud.deadline = time.monotonic() + 120
    version = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    output = path / "reports" / version
    private_dir(output)
    rows = []
    for entry in state["runs"]:
        row = load_row(path, entry)
        try:
            observations = refresh(cloud, row)
            save(output / f"{entry['key']}-observations.json", observations, exclusive=True)
        except Exception as error:  # noqa: BLE001 - preserve evidence without credential-bearing errors
            row["report_read_error"] = type(error).__name__
            row["case1_trace_ready"] = False
        rows.append(row)
    used = {row["key"] for row in rows}
    rows.extend({"key": f"{s}-{n}", "scenario_id": s, "repeat": n,
                 "protocol_status": "NOT RUN"} for s in SCENARIOS for n in (1, 2)
                if f"{s}-{n}" not in used)
    rows.sort(key=lambda row: (SCENARIOS.index(row["scenario_id"]), row["repeat"]))
    report = {"activity_id": state["activity_id"], "created_at": lab.utc(),
              "langfuse_base_url": cloud.base_url, "project_id": "agent-lab",
              "provenance": state.get("provenance", {}),
              "reserved_runs": len(state["runs"]), "max_runs": 6, "runs": rows}
    save(output / "report.json", report, exclusive=True)
    render_report(output, report)
    cloud.deadline = None
    print(json.dumps({"report": str(output / "index.html"),
                      "markdown": str(output / "index.md"),
                      "used_runs": len(state["runs"])}, ensure_ascii=False))
    return report


def run(args):
    values, credentials, cloud, origin = preflight(args.env_file)
    path, state = activity(args.batch, create=True)
    if state.get("config_source", str(args.env_file)) != str(args.env_file):
        raise RuntimeError("CASE1_CONFIG_SOURCE_CHANGED")
    if state.get("langfuse_base_url", origin) != origin:
        raise RuntimeError("CASE1_TARGET_CHANGED")
    if state.get("model", values["LLM_MODEL"]) != values["LLM_MODEL"]:
        raise RuntimeError("CASE1_MODEL_CHANGED")
    state.update(config_source=str(args.env_file), langfuse_base_url=origin,
                 model=values["LLM_MODEL"], project_id="agent-lab")
    count = assert_previous(path, state, args.scenario, cloud, resume=args.resume)
    save(path / "activity.json", state)
    for _ in range(count, 2):
        entry = reserve(path, state, args.scenario)
        row = execute_one(path, state, entry, values, credentials, cloud, args.wait)
        print(json.dumps({"activity_id": state["activity_id"], "case": entry["key"],
                          "run_id": row.get("run_id"), "execution": row["protocol_status"],
                          "ingestion": row["ingestion_state"]}), flush=True)
        if not infrastructure_valid(row) or not row.get("case1_trace_ready"):
            build_report(path, state, cloud)
            raise RuntimeError("CASE1_STOP：执行或摄取不完整；保留已用预算，后续 NOT RUN")
    build_report(path, state, cloud)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "report", "review", "new-activity"))
    parser.add_argument("--env-file", type=Path, default=dev.ENV_FILE)
    parser.add_argument("--scenario", choices=SCENARIOS, default="S01")
    parser.add_argument("--batch")
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--continue", dest="resume", action="store_true")
    parser.add_argument("--wait", type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.wait <= 960:
        parser.error("--wait must be 1..960")
    os.umask(0o077)
    def interrupted(_signum, _frame):
        raise RuntimeError("CASE1_INTERRUPTED")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.command == "preflight":
        _, _, _, origin = preflight(args.env_file)
        print(json.dumps({"status": "PASS", "project": "Agent Lab",
                          "origin": origin, "model_calls": 0}, ensure_ascii=False))
        return
    with lock():
        if args.command == "new-activity":
            path, state = activity(create=True, new=True)
            print(json.dumps({"activity_id": state["activity_id"], "path": str(path)}))
        elif args.command == "run":
            run(args)
        else:
            path, state = activity(args.batch)
            if args.command == "review":
                if not args.reviews:
                    parser.error("--reviews is required")
                reviews = read_json(args.reviews)
                rows = {r.get("run_id"): r for r in
                        (load_row(path, e) for e in state["runs"]) if r.get("run_id")}
                if not reviews or not set(reviews) <= set(rows):
                    raise RuntimeError("CASE1_REVIEW_RUN_MISMATCH")
                for identifier, review in reviews.items():
                    row = rows[identifier]
                    if (review.get("source") != "agent_review" or review.get("status") not in {"PASS", "FAIL"}
                            or review.get("answer_sha256") != content_digest(row.get("final_answer"))
                            or not review.get("reason") or review.get("rubric_version") != "case1-v1"):
                        raise RuntimeError("CASE1_REVIEW_INVALID")
                directory = path / "reviews"
                private_dir(directory)
                name = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4) + ".json"
                save(directory / name, reviews, exclusive=True)
                print(json.dumps({"reviews_imported": len(reviews), "model_calls": 0}))
            else:
                cloud, _ = target(args.env_file)
                build_report(path, state, cloud)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - preserve evidence without credential-bearing errors
        # Never echo endpoint payloads, credentials or raw exception messages.
        print(str(error) if isinstance(error, RuntimeError) and str(error).startswith(
            ("CASE1_", "LANGFUSE_", "BLOCKED:", "STOP:")) else type(error).__name__, file=sys.stderr)
        sys.exit(1)
