"""Explicitly approved, bounded score-only writes. No model, exporter, or Trace creation."""

import argparse
import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import dev
from obs_lab_scores import VERSION, digest, upload_plan


class ScoreCloud:
    def __init__(self, credentials):
        self.credentials = credentials

    def request(self, path, query=None, payload=None):
        if path not in {"projects", "scores", "v3/scores", "v2/observations"}:
            raise ValueError("STOP: endpoint not allowed")
        auth = base64.b64encode((self.credentials["LANGFUSE_PUBLIC_KEY"] + ":" +
                                 self.credentials["LANGFUSE_SECRET_KEY"]).encode()).decode()
        url = "https://jp.cloud.langfuse.com/api/public/" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
        request = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None,
                                        headers={"Authorization": "Basic " + auth,
                                                 "Content-Type": "application/json"})
        remaining = getattr(self, "deadline", time.monotonic() + 20) - time.monotonic()
        if remaining <= 0:
            raise ValueError("BLOCKED: Cloud total time budget exhausted")
        with opener.open(request, timeout=min(20, remaining)) as response:
            return json.load(response)

    def read_score(self, score):
        moment = datetime.fromisoformat(score["timestamp"])
        query = {"id": score["id"], "fromTimestamp": (moment - timedelta(seconds=1)).isoformat(),
                 "toTimestamp": (moment + timedelta(seconds=1)).isoformat(), "limit": 100,
                 "fields": "core,details,subject"}
        result = self.request("v3/scores", query)
        if result.get("meta", {}).get("cursor"):
            raise ValueError("STOP: score ID unexpectedly requires pagination")
        rows = result.get("data", [])
        if len(rows) > 1:
            raise ValueError("STOP: duplicate score identity")
        return rows[0] if rows else None


def same_score(actual, expected):
    # v3 categorical value is the string label, not the legacy numeric mapping.
    return actual.get("subject") == {"kind": "trace", "id": expected["traceId"]} and all(
        actual.get(k) == expected[k] for k in (
        "id", "name", "value", "dataType", "comment", "source", "environment")) and (
        datetime.fromisoformat(actual["timestamp"]) ==
        datetime.fromisoformat(expected["timestamp"]))


def publish(result, approved_sha, max_writes, cloud, journal, wait_seconds=60, sleep=time.sleep):
    cloud.deadline = time.monotonic() + 180
    plan = upload_plan(result)
    if approved_sha != plan["plan_sha256"] or not 0 < len(plan["scores"]) <= max_writes <= 50:
        raise ValueError("STOP: approval hash/write budget mismatch")
    projects = cloud.request("projects").get("data", [])
    if len(projects) != 1 or [projects[0].get("id")] != plan["projects"]:
        raise ValueError("STOP: Cloud project mismatch")
    # Verify every Run/Thread/Trace against Cloud again before any write.
    for row in result["runs"]:
        moment = datetime.fromisoformat(row["score_timestamp"])
        found = cloud.request("v2/observations", {
            "traceId": row["trace_id"], "sessionId": row["thread_id"], "limit": 100,
            "fromStartTime": (moment - timedelta(minutes=10)).isoformat(),
            "toStartTime": (moment + timedelta(seconds=1)).isoformat(),
            "fields": "core,basic,metadata,trace_context"})
        rows = found.get("data", [])
        if found.get("meta", {}).get("cursor") or not rows or any(
                o.get("traceId") != row["trace_id"] or
                o.get("projectId", row["project_id"]) != row["project_id"] or
                o.get("sessionId") not in (None, row["thread_id"]) or
                (o.get("metadata") or {}).get("run_id") not in (None, row["run_id"]) for o in rows):
            raise ValueError("STOP: Trace association ambiguous or read limit exceeded")
        if not any(o.get("sessionId") == row["thread_id"] and
                   (o.get("metadata") or {}).get("run_id") == row["run_id"] for o in rows):
            raise ValueError("STOP: trusted Run/Thread mapping absent")
    pending = []
    for score in plan["scores"]:
        actual = cloud.read_score(score)
        if actual is not None and not same_score(actual, score):
            raise ValueError("STOP: existing Score association/content conflict")
        if actual is None:
            pending.append(score)
    # O_EXCL journal prevents concurrent batches and accidental resubmission after ambiguous I/O.
    with open(journal, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump({"plan_sha256": approved_sha, "state": "STARTED_NO_AUTO_RETRY",
                   "ids": [s["id"] for s in pending]}, stream)
    if pending:
        cloud.request("scores", payload=pending)  # Exactly one bounded batch POST, never retry.
    for attempt in range(3):
        missing = []
        for score in plan["scores"]:
            actual = cloud.read_score(score)
            if actual is None:
                missing.append(score["id"])
            elif not same_score(actual, score):
                raise ValueError("STOP: Score readback mismatch")
        if not missing:
            return {"status": "PASS", "written": len(pending), "verified": len(plan["scores"]),
                    "plan_sha256": approved_sha, "source": "Cloud Scores API v3",
                    "score_trace_pairs": [{"score_id": s["id"], "trace_id": s["traceId"]}
                                          for s in plan["scores"]]}
        if attempt < 2 and wait_seconds:
            sleep(min(5, wait_seconds))
    raise ValueError("BLOCKED: Cloud score ingestion pending; journal retained, no automatic POST retry")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--approved-plan-sha256", required=True)
    parser.add_argument("--max-writes", required=True, type=int)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = json.loads(args.report.read_text())
    if result.get("schema") != VERSION or args.output.exists():
        parser.error("expected versioned offline report and new output")
    if digest(upload_plan(result)["scores"]) != args.approved_plan_sha256:
        parser.error("approved plan differs")
    credentials = dev.read_langfuse_env(args.env_file)
    try:
        outcome = publish(result, args.approved_plan_sha256, args.max_writes,
                          ScoreCloud(credentials), args.journal)
    except Exception as exc:  # noqa: BLE001 - never expose private HTTP response bodies
        # Provider/HTTP error text may contain sensitive body or headers: never echo it.
        if isinstance(exc, ValueError) and str(exc).startswith(("STOP:", "BLOCKED:")):
            raise SystemExit(str(exc)) from None
        raise SystemExit("STOP: Cloud operation failed; retain journal and inspect safely") from None
    with open(args.output, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(outcome, stream, indent=2)
    print(json.dumps({k: outcome[k] for k in ("status", "written", "verified")}))


if __name__ == "__main__":
    main()
