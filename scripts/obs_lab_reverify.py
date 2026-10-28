"""Read-only offline verification of saved Phase A/B evidence. No model or Cloud I/O."""

import argparse
import json
import os
from pathlib import Path

from obs_lab_faults import inspect_faults
from obs_lab_verify import final_answer, history_answer_matches, history_matches, verify_cloud


def reverify(source, reviews):
    from obs_lab import inspect_run

    manifest = json.loads((source / "manifest.json").read_text())
    for row in manifest["runs"]:
        prefix = f"{row['scenario_id']}-{row['repeat']}"
        raw = json.loads((source / f"{prefix}-private.json").read_text())
        state = raw.get("state") or {}
        messages = state.get("values", {}).get("messages", [])
        row.update(inspect_run(state, raw.get("runs") or [], raw.get("events") or []))
        row["history_tool_pairs_valid"] = history_matches(state, raw.get("history"))
        row["fault_evidence"] = inspect_faults(messages, row["scenario_id"])
        row["history_final_answer_valid"] = history_answer_matches(state, raw.get("history"))
        row["final_answer"] = final_answer(messages)
        row["tool_receipts"] = [m for m in messages if m.get("type", m.get("role")) == "tool"]
        row["diagnosis_review"] = reviews.get(row.get("run_id"), {})
        if row["scenario_id"] == "S07":
            row["model_attempts"] = json.loads((source / "model-attempts.json").read_text())
        observations = json.loads((source / f"{prefix}-cloud.json").read_text())
        row["cloud"] = verify_cloud(observations, row, manifest["project_id"])
    return {"source": str(source), "mode": "offline_read_only", "original_stop": manifest.get("stop"),
            "runs": [{k: row.get(k) for k in ("scenario_id", "run_id", "cloud")} for row in manifest["runs"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, help="Run ID -> status/source/answer_sha256; explicit evidence review")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file outside the historical batch")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.is_relative_to(source) or output.exists():
        parser.error("Output must be a new file outside the historical source directory")
    reviews = json.loads(args.reviews.read_text()) if args.reviews else {}
    result = reverify(source, reviews)
    with open(output, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"mode": result["mode"], "results": [r["cloud"]["scenario_observable"] for r in result["runs"]]}))


if __name__ == "__main__":
    main()
