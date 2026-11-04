import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import interview_eval as evaluation
from interview_spans import ExperimentSpans

from kube_triage.prompts import INTERVIEW_SUFFIX, SYSTEM_PROMPT, system_prompt


def test_only_candidate_prompt_changes(monkeypatch):
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("INTERVIEW_EXPERIMENT", "{}")
    monkeypatch.setenv("EVAL_PROMPT_VARIANT", "A")
    assert system_prompt() == SYSTEM_PROMPT
    monkeypatch.setenv("EVAL_PROMPT_VARIANT", "interview-candidate")
    assert system_prompt() == SYSTEM_PROMPT + INTERVIEW_SUFFIX
    monkeypatch.setenv("TRIAGE_ENV", "production")
    assert system_prompt() == SYSTEM_PROMPT


def test_frozen_item_identity_and_experiment_spans():
    items = evaluation.frozen_items()
    assert len({i["id"] for i in items.values()}) == 3
    item = {**items["S06"], "datasetId": "test"}
    request = evaluation.context("activity", "baseline", item, "rev")
    candidate = evaluation.context("activity", "candidate", item, "rev")
    assert request["question"] == candidate["question"]
    assert request["attributes"]["langfuse.experiment.id"] != candidate["attributes"]["langfuse.experiment.id"]
    provider = TracerProvider()
    provider.add_span_processor(ExperimentSpans(request))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("LangGraph") as root:
        with tracer.start_as_current_span("llm") as child:
            child.set_attribute('output.value', '{"messages":[{"type":"ai","data":{"content":"answer"}}]}')
            assert child.attributes["langfuse.experiment.item.root_observation_id"] == f"{root.context.span_id:016x}"
        assert root.attributes["langfuse.observation.output"] == "answer"
    with tracer.start_as_current_span("health") as unrelated:
        assert "langfuse.experiment.id" not in unrelated.attributes


def test_wrong_trace_never_counts_as_an_experiment_match():
    class Api:
        def request(self, *args):
            return {"data": [{"traceId": "different"}]}
    request = evaluation.context("activity", "baseline", {**evaluation.frozen_items()["S01"],
                                 "datasetId": "test"}, "rev")
    with pytest.raises(ValueError, match="identity"):
        evaluation.match_item(Api(), request, {"start": "2026-01-01T12:00:00Z",
                              "cloud": {"trace_id": "actual", "root_id": "root"}})


def test_local_score_timestamp_matches_only_its_exact_millisecond():
    expected = {"id": "score", "traceId": "trace", "name": "a", "value": "PASS", "dataType": "CATEGORICAL",
                    "comment": "reason", "source": "API", "environment": "obs-lab",
                    "timestamp": "2026-11-04T00:00:00.123456+00:00"}
    actual = {**expected, "projectId": "agent-lab", "subject": {"kind": "trace", "id": "trace"},
              "timestamp": "2026-11-04T00:00:00.123Z"}
    assert evaluation.matches_local_score(actual, expected)
    assert not evaluation.matches_local_score({**actual, "value": "FAIL"}, expected)
    assert not evaluation.matches_local_score({**actual, "timestamp": "2026-11-04T00:00:00.124Z"}, expected)
