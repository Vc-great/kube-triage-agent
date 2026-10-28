"""Score publishing contract with an in-memory Cloud, never credentials/network."""

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from obs_lab_score_upload import ScoreCloud, publish
from obs_lab_scores import rule, upload_plan


def report():
    return {"runs": [{"project_id": "p", "batch_id": "b", "run_id": "r", "trace_id": "t",
                      "thread_id": "thread", "score_timestamp": "2026-10-28T00:00:00+00:00",
                      "source_sha256": "sha", "ground_truth_sha256": "gt",
                      "rules": {"tool_protocol_valid": rule(True, "paired")}}]}


class Cloud:
    def __init__(self):
        self.scores = {}
        self.posts = []
        self.project = "p"
        self.trace = "t"
        self.corrupt_readback = False
        self.extra_scores = []
        self.queries = []

    def request(self, path, query=None, payload=None):
        if path == "projects":
            return {"data": [{"id": self.project}]}
        if path == "v2/observations":
            return {"data": [{"traceId": self.trace, "projectId": self.project,
                              "sessionId": "thread", "metadata": {"run_id": "r"}}]}
        if path == "v3/scores":
            self.queries.append(query)
            return {"data": [s for s in [*self.scores.values(), *self.extra_scores]
                             if s["id"] == query["id"]]}
        assert path == "scores"
        assert isinstance(payload, list)
        self.posts.append(deepcopy(payload))
        self.scores.update({s["id"]: deepcopy(s) for s in payload})
        for score in payload:
            self.scores[score["id"]]["subject"] = {"kind": "trace", "id": score["traceId"]}
        if self.corrupt_readback:
            self.scores[payload[0]["id"]]["subject"]["id"] = "wrong"
        return {"message": "Accepted"}

    def read_score(self, expected):
        return ScoreCloud.read_score(self, expected)


def test_upload_readback_and_second_attempt_does_not_post(tmp_path):
    cloud, result = Cloud(), report()
    approval = upload_plan(result)["plan_sha256"]
    first = publish(result, approval, 1, cloud, tmp_path / "first.json", wait_seconds=0)
    second = publish(result, approval, 1, cloud, tmp_path / "second.json", wait_seconds=0)
    assert first["written"] == first["verified"] == 1
    assert second["written"] == 0 and second["verified"] == 1
    assert len(cloud.posts) == 1
    assert all(q == {"id": cloud.posts[0][0]["id"], "limit": 2, "fields": "details,subject"}
               for q in cloud.queries)
    assert (tmp_path / "first.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["hash", "budget", "project", "trace", "existing"])
def test_preflight_stops_before_any_write(tmp_path, failure):
    cloud, result = Cloud(), report()
    plan = upload_plan(result)
    if failure == "project":
        cloud.project = "wrong"
    elif failure == "trace":
        cloud.trace = "wrong"
    elif failure == "existing":
        score = deepcopy(plan["scores"][0])
        score["subject"] = {"kind": "trace", "id": score["traceId"]}
        score["value"] = "FAIL"
        cloud.scores[score["id"]] = score
    with pytest.raises(ValueError, match="STOP"):
        publish(result, "wrong" if failure == "hash" else plan["plan_sha256"],
                0 if failure == "budget" else 1, cloud, tmp_path / "journal.json", wait_seconds=0)
    assert not cloud.posts and not (tmp_path / "journal.json").exists()


def test_ambiguous_readback_stops_and_keeps_journal(tmp_path):
    cloud, result = Cloud(), report()
    cloud.corrupt_readback = True
    journal = tmp_path / "journal.json"
    with pytest.raises(ValueError, match="readback mismatch"):
        publish(result, upload_plan(result)["plan_sha256"], 1, cloud, journal, wait_seconds=0)
    assert journal.exists() and len(cloud.posts) == 1
    with pytest.raises(ValueError, match="conflict"):
        publish(result, upload_plan(result)["plan_sha256"], 1, cloud, journal, wait_seconds=0)
    assert len(cloud.posts) == 1


@pytest.mark.parametrize("timestamp", ["2026-10-28T00:00:05+00:00", "2026-10-29T00:00:00+00:00"])
def test_same_id_different_second_or_day_is_conflict_before_post(tmp_path, timestamp):
    cloud, result = Cloud(), report()
    plan = upload_plan(result)
    existing = {**plan["scores"][0], "subject": {"kind": "trace", "id": "t"}, "timestamp": timestamp}
    cloud.scores[existing["id"]] = existing
    with pytest.raises(ValueError, match="conflict"):
        publish(result, plan["plan_sha256"], 1, cloud, tmp_path / "journal.json")
    assert not cloud.posts
    assert "fromTimestamp" not in cloud.queries[0] and "toTimestamp" not in cloud.queries[0]


def test_duplicate_id_different_dates_stops_before_post(tmp_path):
    cloud, result = Cloud(), report()
    plan = upload_plan(result)
    first = {**plan["scores"][0], "subject": {"kind": "trace", "id": "t"}}
    cloud.scores[first["id"]] = first
    cloud.extra_scores.append({**first, "timestamp": "2026-10-29T00:00:00+00:00"})
    with pytest.raises(ValueError, match="duplicate"):
        publish(result, plan["plan_sha256"], 1, cloud, tmp_path / "journal.json")
    assert not cloud.posts
