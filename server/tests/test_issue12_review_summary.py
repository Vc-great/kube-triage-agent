"""Reject malformed or re-attributed human review data before A/B unblinding."""

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import summarize_issue12_human_review as review


def sample():
    forms, mapping, scores, runs = [], [], [], []
    for arm in "AB":
        for case in "abcdefgh":
            for repeat in (1, 2, 3):
                rid = f"R-{arm}{case}{repeat}"
                tool_id = f"tool-{arm}{case}{repeat}"
                form = {"review_id": rid, "question": "question", "answer": "answer",
                        "tool_message_ids": [tool_id],
                        "model_seen_evidence": [{"tool_call_id": tool_id, "content": "uid-1"}],
                        "independent_ground_truth": "truth", "forbidden_claims": ["claim"],
                        "diagnosis_correct": "PENDING", "grounding_score": "PENDING",
                        "false_positive": "PENDING", "causal_overclaim": "PENDING",
                        "tool_error_handling": "PENDING", "reason": "PENDING",
                        "reviewer": "PENDING", "reviewed_at": "PENDING"}
                forms.append(form)
                score = {**copy.deepcopy(form), "diagnosis_correct": 1, "grounding_score": 2,
                         "false_positive": 0, "causal_overclaim": 0,
                         "tool_error_handling": "NA", "reason": f"Evidence {tool_id}",
                         "reviewer": "human", "reviewed_at": "2026-10-14T21:00:00+08:00"}
                scores.append(score)
                mapping.append({"review_id": rid, "arm": arm, "case_id": case,
                                "repeat": repeat, "thread_id": f"thread-{rid}",
                                "run_id": f"run-{rid}"})
                runs.append({"arm": arm, "case_id": case, "repeat": repeat,
                             "thread_id": f"thread-{rid}", "run_id": f"run-{rid}",
                             "run_status": "success", "tool_message_match": True,
                             "tool_failure_count": 0,
                             "dataset_sha": review.FROZEN_DATASET_SHA,
                             "fixture_bundle_sha": review.FROZEN_FIXTURES_SHA,
                             "graph_sha": review.sha256(review.ROOT / "server/src/kube_triage/graph.py"),
                             "prompt_sha": review.FROZEN_PROMPT_SHA[arm]})
    return forms, mapping, scores, runs


def test_complete_review_pairs():
    forms, mapping, scores, runs = sample()
    by_map, by_score, by_run = review.validate_rows(forms, mapping, scores, runs)
    assert len(by_map) == len(by_score) == len(by_run) == 48


@pytest.mark.parametrize("change", [
    lambda f, m, s, r: s.pop(),
    lambda f, m, s, r: s[1].update(review_id=s[0]["review_id"]),
    lambda f, m, s, r: s[0].update(grounding_score=True),
    lambda f, m, s, r: s[0].update(tool_message_ids=["unrelated"]),
    lambda f, m, s, r: s[0]["model_seen_evidence"][0].update(content="uid-conflict"),
    lambda f, m, s, r: s[0].update(reason="No tool citation"),
    lambda f, m, s, r: m[0].update(repeat=2),
    lambda f, m, s, r: r[0].update(tool_failure_count=1),
])
def test_invalid_review_rejected(change):
    forms, mapping, scores, runs = copy.deepcopy(sample())
    change(forms, mapping, scores, runs)
    with pytest.raises(ValueError):
        review.validate_rows(forms, mapping, scores, runs)
