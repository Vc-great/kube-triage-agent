"""Explicitly budgeted S09/S10 real-run collection. Requires separate human approval."""

import argparse
import json
import os
import secrets
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from eval_phase3a import api, private_directory, write_private
from obs_lab import Cloud, configuration, inspect_run, isolated, run_deadline, utc
from obs_lab_phase_c import SUMMARY_MAX_TURNS, grounding_question, summary_question
from obs_lab_scores import current_round, frozen_cases, score_run, turn_evidence
from obs_lab_verify import decoded, history_matches, verify_native


def collect_turn(base, token, thread, scenario, batch, turn, timeout, output):
    question = summary_question(turn) if scenario == "S09" else grounding_question()
    payload = {"assistant_id": "agent", "stream_mode": ["values"],
               "metadata": {"environment": "obs-lab", "batch_id": batch, "scenario_id": scenario,
                            "case_version": "issue12-blind-v1-phase-c1", "turn": turn},
               "input": {"messages": [{"role": "human", "content": question}]}}
    request = urllib.request.Request(base + f"/threads/{thread}/runs/stream",
        data=json.dumps(payload).encode(), headers={"X-Api-Key": token, "Content-Type": "application/json"})
    before = {r["run_id"] for r in api(base, token, f"/threads/{thread}/runs")}
    raw = {"thread_id": thread, "events": [], "prior_run_ids": sorted(before)}
    write_private(output, raw)
    start, started = time.monotonic(), utc()
    try:
        with run_deadline(timeout), urllib.request.urlopen(request, timeout=timeout) as response:
            kind, lines = "", []
            for line in response:
                line = line.decode().rstrip("\r\n")
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    lines.append(line[5:].strip())
                elif not line and (kind or lines):
                    raw["events"].append({"event": kind, "data": "\n".join(lines)})
                    kind, lines = "", []
            if kind or lines:
                raw["events"].append({"event": kind, "data": "\n".join(lines)})
    finally:
        for key in ("state", "history", "runs"):
            try:
                raw[key] = api(base, token, f"/threads/{thread}/{key}")
            except (OSError, ValueError):
                raw[key] = None
        write_private(output, raw)
    # State is cumulative on S09; inspect the current round and its uniquely new Run.
    messages = (raw.get("state") or {}).get("values", {}).get("messages", [])
    runs = [r for r in raw.get("runs") or [] if r.get("run_id") not in before
            and r.get("thread_id") == thread]
    if len(runs) != 1:
        raise ValueError("STOP: current turn Run identity ambiguous")
    state = {"values": {"messages": current_round(messages)}}
    row = {"scenario_id": scenario, "repeat": turn, "thread_id": thread, "start": started,
           "end": utc(), "elapsed_seconds": time.monotonic() - start,
           **inspect_run(state, runs, raw["events"])}
    row["history_tool_pairs_valid"] = history_matches(raw.get("state") or {}, raw.get("history"))
    if row["protocol_status"] != "success" or row["sse_error"] or not any(
            e["event"] == "end" for e in raw["events"]) or not row["tool_pairs_valid"]:
        raise ValueError("STOP: protocol/tool pairing failed; preserve private evidence")
    row["rule_checks"] = score_run(row, turn_evidence(raw),
                                   frozen_cases()["h" if scenario == "S09" else "g"])
    return row


def summary_outcomes(observations):
    result = []
    for obs in observations:
        if obs.get("name") == "context_summary_outcome":
            output = decoded(obs.get("output"))
            if isinstance(output, dict):
                result.extend(output.get("context_summary_outcomes") or [])
    return result


def run_sequence(scenario, max_runs, run_turn):
    """One Run per turn, same Thread managed by caller. No retry or silent continuation."""
    rows = []
    for turn in range(1, max_runs + 1):
        row = run_turn(turn)
        rows.append(row)
        if scenario == "S10" or row.get("summary_outcomes"):
            return rows
    raise ValueError("BLOCKED: S09 Summary not observed within approved Run budget")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=("S09", "S10"))
    parser.add_argument("--approved-max-runs", required=True, type=int)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args()
    if not (1 <= args.approved_max_runs <= SUMMARY_MAX_TURNS and 30 <= args.timeout <= 180) or (
            args.scenario == "S10" and args.approved_max_runs != 1):
        parser.error("S09 requires 1..10 approved Runs; S10 exactly 1; timeout 30..180 seconds")
    if args.output.exists():
        parser.error("output must be new")
    os.umask(0o077)
    frozen_cases()
    values, credentials = configuration(args.env_file)
    values["OBS_LAB_SCENARIO"] = args.scenario
    private_directory(args.output)
    batch = "issue92-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    cloud = Cloud(credentials)
    projects = cloud.get("projects").get("data", [])
    if len(projects) != 1 or not projects[0].get("id"):
        raise ValueError("STOP: Cloud project not unique")
    manifest = {"batch_id": batch, "project_id": projects[0]["id"], "runs": [],
                "max_runs": args.approved_max_runs, "concurrency": 1, "start": utc()}
    write_private(args.output / "manifest.json", manifest)
    try:
        with isolated(values, credentials, args.output) as (base, token):
            thread = api(base, token, "/threads", "POST", {})["thread_id"]

            def turn(number):
                prefix = args.output / f"{args.scenario}-{number}"
                row = collect_turn(base, token, thread, args.scenario, batch, number, args.timeout,
                                   Path(str(prefix) + "-private.json"))
                manifest["runs"].append(row)
                write_private(args.output / "manifest.json", manifest)
                # A bounded, read-only poll, never a second model Run to repair ingestion.
                cloud.deadline = time.monotonic() + 120
                for attempt in range(25):
                    observations = cloud.observations(row, row["start"], utc())
                    write_private(Path(str(prefix) + "-cloud.json"), observations)
                    outcomes = summary_outcomes(observations)
                    expected = row["model_decisions"] + sum(o.get("summary_calls", 0) for o in outcomes)
                    row["cloud"] = verify_native(observations, {**row, "model_decisions": expected}, manifest["project_id"])
                    if row["cloud"]["chain_verified"]:
                        row["summary_outcomes"] = outcomes
                        write_private(args.output / "manifest.json", manifest)
                        return row
                    if attempt < 24:
                        time.sleep(5)
                raise ValueError("BLOCKED: Cloud chain not verified; no additional Run")

            run_sequence(args.scenario, args.approved_max_runs, turn)
    except Exception as exc:  # noqa: BLE001 - do not expose private HTTP exception bodies
        manifest["stop"] = str(exc) if isinstance(exc, ValueError) and str(exc).startswith(
            ("STOP:", "BLOCKED:")) else "STOP: collection failed; private evidence retained"
        raise SystemExit(manifest["stop"]) from None
    finally:
        manifest["end"] = utc()
        write_private(args.output / "manifest.json", manifest)


if __name__ == "__main__":
    main()
