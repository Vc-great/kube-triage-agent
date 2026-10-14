"""Validate confirmed Issue #12 scores and write a private descriptive A/B summary."""

import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from eval_issue12 import (
    FROZEN_DATASET_SHA,
    FROZEN_FIXTURES_SHA,
    FROZEN_PROMPT_SHA,
    ROOT,
    sha256,
)

IMMUTABLE = ("question", "answer", "tool_message_ids", "model_seen_evidence",
             "independent_ground_truth", "forbidden_claims")
SCORE_VALUES = {"diagnosis_correct": {0, 1}, "grounding_score": {0, 1, 2},
                "false_positive": {0, 1}, "causal_overclaim": {0, 1}}
HUMAN_FIELDS = ("reason", "reviewer", "reviewed_at")
EXPECTED = {(arm, case, repeat) for arm in "AB" for case in "abcdefgh"
            for repeat in (1, 2, 3)}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_index(rows, key, expected_count=48):
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError("Incomplete 48-row input")
    result = {}
    for row in rows:
        item_key = key(row)
        if item_key in result:
            raise ValueError("Duplicate review or run key")
        result[item_key] = row
    return result


def validate_rows(forms, mapping, scores, runs):
    by_form = unique_index(forms, lambda x: x["review_id"])
    by_map = unique_index(mapping, lambda x: x["review_id"])
    by_score = unique_index(scores, lambda x: x["review_id"])
    by_run = unique_index(runs, lambda x: (x["arm"], x["case_id"], x["repeat"]))
    if (set(by_form) != set(by_map) or set(by_form) != set(by_score) or
            set(by_run) != EXPECTED or
            {(x["arm"], x["case_id"], x["repeat"]) for x in mapping} != EXPECTED):
        raise ValueError("Missing or mismatched A/B pair")
    if (len({x["thread_id"] for x in runs}) != 48 or
            len({x["run_id"] for x in runs}) != 48):
        raise ValueError("Duplicate Thread or Run ID")
    for rid, score in by_score.items():
        form, item = by_form[rid], by_map[rid]
        run = by_run[item["arm"], item["case_id"], item["repeat"]]
        if set(score) != set(form) or any(score[k] != form[k] for k in IMMUTABLE):
            raise ValueError("Scored form changed frozen evidence")
        if (item["thread_id"] != run["thread_id"] or item["run_id"] != run["run_id"] or
                run["run_status"] != "success" or not run["tool_message_match"] or
                run["dataset_sha"] != FROZEN_DATASET_SHA or
                run["fixture_bundle_sha"] != FROZEN_FIXTURES_SHA or
                run["graph_sha"] != sha256(ROOT / "server/src/kube_triage/graph.py") or
                run["prompt_sha"] != FROZEN_PROMPT_SHA[item["arm"]]):
            raise ValueError("Run or mapping mismatch")
        for field, values in SCORE_VALUES.items():
            value = score[field]
            if type(value) is not int or value not in values:
                raise ValueError("Illegal human score")
        handling = score["tool_error_handling"]
        if ((run["tool_failure_count"] == 0 and handling != "NA") or
                (run["tool_failure_count"] > 0 and (type(handling) is not int or
                 handling not in {0, 1}))):
            raise ValueError("Tool-error NA or score inconsistent with run")
        if not all(isinstance(score[k], str) and score[k].strip() and
                   score[k] != "PENDING" for k in HUMAN_FIELDS):
            raise ValueError("Missing reason, reviewer or timestamp")
        if datetime.fromisoformat(score["reviewed_at"]).tzinfo is None:
            raise ValueError("Review timestamp needs timezone")
        ids = score["tool_message_ids"]
        if (not ids or len(ids) != len(set(ids)) or
                not any(tool_id in score["reason"] for tool_id in ids)):
            raise ValueError("Reason must cite a corresponding ToolMessage ID")
    return by_map, by_score, by_run


def summarize(by_map, by_score, by_run):
    by_key = {(item["arm"], item["case_id"], item["repeat"]):
              by_score[rid] for rid, item in by_map.items()}
    result = {"status": "USER_CONFIRMED_ALL_48", "denominator": {"runs": 48,
              "per_arm": 24, "paired_case_repeat": 24, "base_scenarios": 8},
              "quality": {}, "rule": {}, "paired": {}, "scenario": {}}
    for arm in "AB":
        group = [by_key[arm, case, repeat] for case in "abcdefgh"
                 for repeat in (1, 2, 3)]
        rules = [by_run[arm, case, repeat] for case in "abcdefgh"
                 for repeat in (1, 2, 3)]
        result["quality"][arm] = {
            "diagnosis_correct": sum(x["diagnosis_correct"] for x in group),
            "grounding_distribution": dict(sorted(Counter(x["grounding_score"] for x in group).items())),
            "grounding_mean": statistics.mean(x["grounding_score"] for x in group),
            "false_positive": sum(x["false_positive"] for x in group),
            "causal_overclaim": sum(x["causal_overclaim"] for x in group),
            "tool_error_handling": dict(Counter(str(x["tool_error_handling"]) for x in group)),
        }
        result["rule"][arm] = {
            "run_success": sum(x["run_status"] == "success" for x in rules),
            "tool_message_match": sum(x["tool_message_match"] for x in rules),
            "tool_selection_compliant": sum(x["tool_selection_compliant"] for x in rules),
            "evidence_sufficient": sum(x["evidence_sufficient"] for x in rules),
            "tool_calls": sum(x["tool_call_count"] for x in rules),
            "tool_failures": sum(x["tool_failure_count"] for x in rules),
            "duplicate_tool_calls": sum(x["duplicate_tool_calls"] for x in rules),
            "budget_limit_exceeded": sum(x["budget_limit_exceeded"] for x in rules),
            "latency_median_seconds": statistics.median(x["elapsed_seconds"] for x in rules),
            "total_tokens_median": statistics.median(x["token_usage"]["total_tokens"]
                                                     for x in rules),
        }
    for field in SCORE_VALUES:
        diffs = [by_key["B", case, repeat][field] - by_key["A", case, repeat][field]
                 for case in "abcdefgh" for repeat in (1, 2, 3)]
        higher_good = field in {"diagnosis_correct", "grounding_score"}
        result["paired"][field] = {
            "b_minus_a_mean": statistics.mean(diffs),
            "b_better": sum((x > 0) if higher_good else (x < 0) for x in diffs),
            "same": sum(x == 0 for x in diffs),
            "b_worse": sum((x < 0) if higher_good else (x > 0) for x in diffs),
        }
    for case in "abcdefgh":
        result["scenario"][case] = {
            field: {arm: [by_key[arm, case, repeat][field] for repeat in (1, 2, 3)]
                    for arm in "AB"} for field in SCORE_VALUES}
    return result


def run(review_dir):
    source = review_dir.parent
    manifest = read(review_dir / "source-manifest.json")
    if any(sha(source / name) != digest for name, digest in manifest.items()):
        raise ValueError("Original run evidence changed")
    attestation = read(review_dir / "human-review-attestation.json")
    scores_path = review_dir / "reviews-human-v1.json"
    if (attestation["status"] != "USER_CONFIRMED_ALL_48" or
            attestation["scores_sha256"] != sha(scores_path)):
        raise ValueError("Human confirmation missing or score hash mismatch")
    forms = read(review_dir / "blind-review-forms.json")
    mapping = read(review_dir / "blind-id-map.json")["mapping"]
    scores = read(scores_path)
    runs = read(source / "runs.json")
    by_map, by_score, by_run = validate_rows(forms, mapping, scores, runs)
    for item in mapping:
        k = item["arm"], item["case_id"], item["repeat"]
        trace = read(source / item["private_trace_file"])
        tools = [m for m in trace["state"]["values"]["messages"] if m.get("type") == "tool"]
        score = by_score[item["review_id"]]
        if (trace["thread_id"] != by_run[k]["thread_id"] or
                trace["runs"][-1]["run_id"] != by_run[k]["run_id"] or
                [m["tool_call_id"] for m in tools] != score["tool_message_ids"] or
                [m["content"] for m in tools] !=
                [e["content"] for e in score["model_seen_evidence"]]):
            raise ValueError("ToolMessage is not from the mapped Run")
    result = summarize(by_map, by_score, by_run)
    result["provenance"] = {"scores_sha256": sha(scores_path),
                            "human_attestation_sha256": sha(review_dir / "human-review-attestation.json"),
                            "source_reviewer_label": attestation["source_reviewer_label"],
                            "confirmation_recorded_at": attestation["confirmation_recorded_at"]}
    output = review_dir / "quality-ab-summary.json"
    with output.open("x", encoding="utf-8") as stream:
        output.chmod(0o600)
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "output": str(output),
                      "paired": result["denominator"]["paired_case_repeat"]}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    run(parser.parse_args().review_dir)
