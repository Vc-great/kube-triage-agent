"""S09 roles from trusted callback parentage, without dropping any Observation."""

from obs_lab_verify import decoded, verify_native


def summary_roles(observations):
    by_id = {o.get("id"): o for o in observations}
    wrappers = [o for o in observations if o.get("name") == "context_summary_outcome"]
    ids, outcomes, missing = set(), [], []
    for wrapper in wrappers:
        output = decoded(wrapper.get("output"))
        records = output.get("context_summary_outcomes") if isinstance(output, dict) else None
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            missing.append("summary_audit_missing")
            continue
        record = records[0]
        if record.get("status") not in {"adopted", "fallback", "cache_hit", "skipped_failed"} or (
                type(record.get("summary_calls")) is not int or record["summary_calls"] not in (0, 1)):
            missing.append("summary_audit_invalid")
            continue
        children = set()
        for observation in observations:
            if observation.get("type") != "GENERATION":
                continue
            parent, visited = observation.get("parentObservationId"), set()
            while parent and parent not in visited:
                if parent == wrapper.get("id"):
                    children.add(observation["id"])
                    break
                visited.add(parent)
                parent = by_id.get(parent, {}).get("parentObservationId")
        if len(children) != record["summary_calls"]:
            missing.append("summary_generation_count")
        ids.update(children)
        outcomes.append(record)
    return ids, outcomes, missing


def verify_context_cloud(observations, row, project):
    # Verify identity first; don't classify generations belonging to another Trace.
    initial = verify_native(observations, row, project)
    if not initial["trace_verified"]:
        return initial
    selected = [o for o in observations if o.get("traceId") == initial["trace_id"]]
    ids, outcomes, missing = summary_roles(selected)
    expected = row["model_decisions"] + sum(r["summary_calls"] for r in outcomes)
    result = verify_native(observations, {**row, "model_decisions": expected}, project,
                           summary_generation_ids=ids)
    result["summary_generation_ids"] = sorted(ids)
    result["summary_outcomes"] = outcomes
    result["missing"].extend(missing)
    if missing:
        result.update(chain_verified=False, chain_status="BLOCKED")
    return result
