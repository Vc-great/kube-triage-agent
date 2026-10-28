"""Pure Phase A/B evidence validation: existence is separate from a proven chain."""

import hashlib
import json
from collections import Counter
from datetime import datetime


def decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def objects(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            # User/tool text is data, not a serialized ToolMessage or Tool Call.
            if key not in {"content", "text"}:
                yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def signature(name, arguments):
    args = decoded(arguments)
    if name in {"events_list", "pods_list_in_namespace"} and isinstance(args, str):
        args = {"namespace": args}
    if not isinstance(args, dict):
        return None
    args = dict(args)
    if name == "pods_log":
        args.setdefault("tail", 20)
    return name, json.dumps(args, sort_keys=True, ensure_ascii=False)


def cloud_calls(value):
    calls = {}
    for item in objects(decoded(value)):
        for call in item.get("tool_calls", []) if isinstance(item.get("tool_calls"), list) else []:
            function = call.get("function", call)
            identifier = call.get("id")
            sig = signature(function.get("name"), function.get("arguments", function.get("args")))
            if not identifier or sig is None:
                continue
            if identifier in calls and calls[identifier] != sig:
                return None
            calls[identifier] = sig
    return calls


def cloud_tool_ids(value):
    return {item["tool_call_id"] for item in objects(decoded(value))
            if isinstance(item.get("tool_call_id"), str)}


def message_pairs(messages):
    calls = [call for msg in messages if msg.get("type", msg.get("role")) in {"ai", "assistant"}
             for call in msg.get("tool_calls", [])]
    tools = [msg for msg in messages if msg.get("type", msg.get("role")) == "tool"]
    ids = [call.get("id") for call in calls]
    paired = (bool(ids) and all(isinstance(i, str) and i for i in ids)
              and len(set(ids)) == len(ids)
              and Counter(ids) == Counter(msg.get("tool_call_id") for msg in tools))
    return calls, tools, paired


def history_matches(state, history):
    calls, tools, paired = message_pairs(state.get("values", {}).get("messages", []))
    if not paired or not isinstance(history, list):
        return False

    def projection(c, t):
        return ([(x.get("id"), signature(x.get("name"), x.get("args"))) for x in c],
                [(x.get("tool_call_id"), x.get("status"), x.get("content")) for x in t])

    def model_sequence(messages):
        return [(msg.get("response_metadata", {}).get("model_name") or
                 msg.get("response_metadata", {}).get("model"),
                 [call.get("id") for call in msg.get("tool_calls", [])])
                for msg in messages if msg.get("type", msg.get("role")) in {"ai", "assistant"}]

    expected = projection(calls, tools)
    expected_models = model_sequence(state.get("values", {}).get("messages", []))
    for snapshot in history:
        c, t, matched = message_pairs(snapshot.get("values", {}).get("messages", []))
        if (matched and projection(c, t) == expected
                and model_sequence(snapshot.get("values", {}).get("messages", [])) == expected_models):
            return True
    return False


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def verify_native(observations, row, project):
    result = {"status": "ingestion_pending", "trace_verified": False, "chain_verified": False,
              "chain_status": "BLOCKED", "timeline_status": "UNKNOWN",
              "tool_call_id_status": "NOT RUN", "missing": []}
    candidates = {obs.get("traceId") for obs in observations
                  if obs.get("sessionId") == row.get("thread_id")
                  and (obs.get("metadata") or {}).get("run_id") == row.get("run_id")
                  and row.get("run_id")}
    candidates.discard(None)
    if len(candidates) != 1:
        result.update(status="unknown" if candidates else "ingestion_pending",
                      missing=["unique_run_trace_mapping"])
        return result
    trace_id = next(iter(candidates))
    selected = [obs for obs in observations if obs.get("traceId") == trace_id]
    if any((o.get("sessionId") and o["sessionId"] != row["thread_id"])
           or ((o.get("metadata") or {}).get("run_id") not in {None, row["run_id"]})
           or (o.get("projectId") not in {None, project}) for o in selected):
        result.update(status="unknown", missing=["conflicting_runtime_identity"])
        return result
    result.update(status="verified", trace_verified=True, trace_id=trace_id,
                  url=f"https://jp.cloud.langfuse.com/project/{project}/traces/{trace_id}")
    generations = [o for o in selected if o.get("type") == "GENERATION"]
    tools = [o for o in selected if o.get("type") == "TOOL"]
    by_id = {o.get("id"): o for o in selected}
    roots = [o for o in selected if not o.get("parentObservationId")]
    result.update(generation_count=len(generations), tool_count=len(tools))
    missing = result["missing"]
    if len(roots) != 1 or len(by_id) != len(selected) or None in by_id:
        missing.append("complete_unique_root")
    root_id = roots[0]["id"] if len(roots) == 1 else None
    result["root_id"] = root_id

    def path_to_root(observation):
        visited = set()
        while observation:
            identifier = observation.get("id")
            start, end = timestamp(observation.get("startTime")), timestamp(observation.get("endTime"))
            if identifier in visited or start is None or end is None or start > end:
                return False
            visited.add(identifier)
            parent_id = observation.get("parentObservationId")
            if not parent_id:
                return identifier == root_id
            parent = by_id.get(parent_id)
            if parent is None:
                return False
            pstart, pend = timestamp(parent.get("startTime")), timestamp(parent.get("endTime"))
            if pstart is None or pend is None or pstart > start or pend < end:
                return False
            observation = parent
        return False

    def ancestors(observation):
        identifiers = set()
        while observation and observation.get("id") not in identifiers:
            identifiers.add(observation.get("id"))
            observation = by_id.get(observation.get("parentObservationId"))
        return identifiers

    phase_b = row.get("scenario_id") in {"S04", "S05", "S06", "S07", "S08"}
    business = [o for o in selected if o.get("name") == "reader_outcome"] if phase_b else []
    if not all(path_to_root(o) for o in selected):
        missing.append("complete_parent_tree")
    calls = row.get("tool_calls") or []
    if not row.get("tool_pairs_valid"):
        missing.append("state_tool_pairing")
    if not row.get("history_tool_pairs_valid"):
        missing.append("history_tool_pairing")
    if len(generations) != row.get("model_decisions") or len(generations) < 2:
        missing.append("all_generations")
    if not calls or len(tools) != len(calls):
        missing.append("all_reader_tools")
    used = set()
    proof = []
    for call in calls:
        identifier, name = call.get("id"), call.get("name")
        sig = signature(name, call.get("args"))
        if not identifier or sig is None:
            missing.append("invalid_local_call")
            continue
        requests = [g for g in generations if (cloud_calls(g.get("output")) or {}).get(identifier) == sig]
        candidates = [t for t in tools if t.get("name") == name and
                      signature(name, decoded(t.get("input"))) == sig and t.get("id") not in used]
        if phase_b:
            # Identical arguments may occur twice in one model decision. A trusted
            # business Runnable carries the actual Call ID and owns its native Tool.
            owners = [o for o in business if isinstance(decoded(o.get("output")), dict)
                      and decoded(o["output"]).get("tool_call_id") == identifier
                      and decoded(o["output"]).get("tool_name") == name]
            candidates = ([t for t in candidates if owners[0]["id"] in ancestors(t)]
                          if len(owners) == 1 else [])
        matches = []
        for left in requests:
            left_end = timestamp(left.get("endTime"))
            later = [g for g in generations if g["id"] != left["id"]
                     and timestamp(g.get("startTime")) is not None and left_end is not None
                     and timestamp(g["startTime"]) >= left_end]
            next_start = min((timestamp(g["startTime"]) for g in later), default=None)
            responses = [g for g in later if timestamp(g["startTime"]) == next_start
                         and identifier in cloud_tool_ids(g.get("input"))]
            for tool in candidates:
                for right in responses:
                    times = [timestamp(left.get("endTime")), timestamp(tool.get("startTime")),
                             timestamp(tool.get("endTime")), timestamp(right.get("startTime"))]
                    if (left["id"] != right["id"] and all(t is not None for t in times)
                            and times == sorted(times)
                            and all(path_to_root(o) for o in (left, tool, right))):
                        matches.append((left, tool, right))
        if len(matches) != 1:
            missing.append("request_tool_response:" + str(identifier))
            continue
        left, tool, right = matches[0]
        used.add(tool["id"])
        proof.append({"tool_call_id": identifier, "request_generation": left["id"],
                      "tool_observation": tool["id"], "response_generation": right["id"]})
    result["tool_call_proof"] = proof
    result["tool_call_id_source"] = (
        "Cloud Generation output/input IDs + Tool name/arguments/time + State/History pairing; "
        "Tool Span itself need not carry a direct Tool Call ID")
    if phase_b:
        records = (row.get("fault_evidence") or {}).get("records", [])
        if len(business) != len(calls) or len(records) != len(calls):
            missing.append("all_business_outcomes")
        business_proof = []
        for record in records:
            matches = [o for o in business if isinstance(decoded(o.get("output")), dict)
                       and decoded(o["output"]).get("tool_call_id") == record["tool_call_id"]
                       and decoded(o["output"]).get("tool_name") == record["name"]
                       and decoded(o["output"]).get("tool_outcome") == record["outcome"]
                       and decoded(o["output"]).get("wrapper_success") == record["wrapper_success"]]
            bridge = next((p for p in proof if p["tool_call_id"] == record["tool_call_id"]), None)
            if len(matches) != 1 or not bridge:
                missing.append("business_outcome:" + str(record["tool_call_id"]))
                continue
            obs, tool = matches[0], by_id[bridge["tool_observation"]]
            # The business wrapper must enclose this exact native Tool execution.
            if obs["id"] not in ancestors(tool) or not path_to_root(obs):
                missing.append("business_tool_parent:" + str(record["tool_call_id"]))
            business_proof.append({"tool_call_id": record["tool_call_id"],
                                   "observation_id": obs["id"], "outcome": record["outcome"]})
        result["business_proof"] = business_proof
        if missing:
            result["status"] = "ingestion_pending"
    result["chain_verified"] = not missing
    if not missing:
        result.update(chain_status="PASS", timeline_status="PASS", tool_call_id_status="PASS")
    return result


def content_digest(content):
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def final_answer(messages):
    assistants = [m for m in messages if m.get("type", m.get("role")) in {"ai", "assistant"}]
    if not assistants or assistants[-1].get("tool_calls"):
        return None
    return assistants[-1].get("content") or None


def history_answer_matches(state, history):
    answer = final_answer(state.get("values", {}).get("messages", []))
    return bool(answer and isinstance(history, list) and any(
        history_matches(state, [snapshot])
        and final_answer(snapshot.get("values", {}).get("messages", [])) == answer
        for snapshot in history))


def verify_cloud(observations, row, project):
    """Keep the native gate intact; prove Phase B independently, never synthesize spans."""
    result = verify_native(observations, row, project)
    native_missing = [m for m in result["missing"] if m != "all_business_outcomes"
                      and not m.startswith(("business_outcome:", "business_tool_parent:"))]
    result["native_missing"] = native_missing
    result.update(native_trace_complete=("PASS" if result["trace_verified"] and not native_missing else
                                        "FAIL" if result["trace_verified"] else "UNKNOWN"),
                  scenario_observable="BLOCKED", diagnosis_behavior="UNKNOWN", event_result="NOT RUN",
                  scenario_missing=[], cancelled_tool_calls=[], scenario_proof=[],
                  evidence_source="Cloud Observations v2 + State/History; no synthetic observations")
    if row.get("scenario_id") not in {"S04", "S05", "S06", "S07", "S08"}:
        result["scenario_observable"] = "PASS" if result["chain_verified"] else "BLOCKED"
        return result
    missing = result["scenario_missing"]
    if not result["trace_verified"]:
        missing.extend(result["missing"])
        return result
    selected = [o for o in observations if o.get("traceId") == result["trace_id"]]
    by_id = {o.get("id"): o for o in selected}
    generations = [o for o in selected if o.get("type") == "GENERATION"]
    business = [o for o in selected if o.get("name") == "reader_outcome" and o.get("type") == "CHAIN"]
    records = (row.get("fault_evidence") or {}).get("records", [])
    calls = row.get("tool_calls") or []
    if (row.get("protocol_status") != "success" or row.get("sse_error")
            or not 2 <= row.get("model_decisions", 0) <= 4 or len(calls) > 6):
        missing.append("run_protocol_or_budget")
    if not row.get("history_final_answer_valid"):
        missing.append("history_final_answer")
    if (len(records) != len(calls) or len(business) != len(calls)
            or Counter(r.get("tool_call_id") for r in records) != Counter(c.get("id") for c in calls)):
        missing.append("all_business_outcomes")
    allowed_native_missing = set()
    used_business = set()
    native_proof = {p["tool_call_id"]: p for p in result.get("tool_call_proof", [])}
    for call in calls:
        identifier, name = call.get("id"), call.get("name")
        sig = signature(name, call.get("args"))
        record_matches = [r for r in records if r.get("tool_call_id") == identifier and r.get("name") == name]
        if len(record_matches) != 1:
            missing.append("local_business_record:" + str(identifier))
            continue
        record = record_matches[0]
        owners = [o for o in business if decoded(o.get("output")) == {
            "tool_call_id": identifier, "tool_name": name, "tool_outcome": record.get("outcome"),
            "wrapper_success": record.get("wrapper_success")}]
        if len(owners) != 1 or owners[0]["id"] in used_business:
            missing.append("business_outcome:" + str(identifier))
            continue
        owner = owners[0]
        if by_id.get(owner.get("parentObservationId"), {}).get("name") != "tools":
            missing.append("business_parent:" + str(identifier))
        used_business.add(owner["id"])
        bridges = []
        for left in generations:
            if sig is None or (cloud_calls(left.get("output")) or {}).get(identifier) != sig:
                continue
            left_end = timestamp(left.get("endTime"))
            later = [g for g in generations if timestamp(g.get("startTime")) is not None
                     and left_end is not None and timestamp(g["startTime"]) >= left_end and g != left]
            next_start = min((timestamp(g["startTime"]) for g in later), default=None)
            for right in later:
                times = [left_end, timestamp(owner.get("startTime")), timestamp(owner.get("endTime")),
                         timestamp(right.get("startTime"))]
                if (timestamp(right["startTime"]) == next_start
                        and identifier in cloud_tool_ids(right.get("input"))
                        and all(t is not None for t in times) and times == sorted(times)):
                    bridges.append((left, right))
        if len(bridges) != 1:
            missing.append("business_request_response:" + str(identifier))
            continue
        left, right = bridges[0]
        if identifier not in native_proof:
            # Only the already reproduced wait_for cancellation of this injected tool.
            eligible = (row.get("scenario_id") == "S04" and name == "pods_log"
                        and call.get("args", {}).get("namespace") == "kube-triage-demo"
                        and call.get("args", {}).get("name") == "sample-a"
                        and timestamp(owner.get("startTime")) is not None
                        and timestamp(owner.get("endTime")) is not None
                        and timestamp(owner["endTime"]) - timestamp(owner["startTime"]) >= 8
                        and record.get("outcome") == "timeout" and record.get("wrapper_success") is False
                        and not any(o.get("type") == "TOOL" and o.get("name") == name
                                    and signature(name, o.get("input")) == sig for o in selected))
            if not eligible:
                missing.append("unexpected_native_tool_missing:" + str(identifier))
                continue
            result["cancelled_tool_calls"].append(identifier)
            allowed_native_missing.update({"all_reader_tools", "request_tool_response:" + identifier,
                                           "business_outcome:" + identifier})
        result["scenario_proof"].append({"tool_call_id": identifier, "business_observation": owner["id"],
                                         "request_generation": left["id"], "response_generation": right["id"],
                                         "outcome": record.get("outcome")})
    missing.extend(m for m in result["missing"] if m not in allowed_native_missing)
    if len([o for o in selected if o.get("type") == "TOOL"]) != len(calls) - len(result["cancelled_tool_calls"]):
        missing.append("unexpected_native_tool_count")
    if result["cancelled_tool_calls"]:
        result["cancellation_evidence"] = "PR #97 Cloud S04 + locked SDK wait_for reproduction; docs/issue91-phase-b-validation.md"
    expected = {"S04": ("pods_log", "timeout", False), "S05": ("pods_get", "permission_denied", False),
                "S06": ("pods_log", "business_error", True)}.get(row.get("scenario_id"))
    if expected:
        if not any((r.get("name"), r.get("outcome"), r.get("wrapper_success")) == expected
                   and c.get("args", {}).get("name") == "sample-a"
                   for r in records for c in calls if c.get("id") == r.get("tool_call_id")):
            missing.append("expected_fault_classification")
        if any(r.get("outcome") != "success" and (r.get("name"), r.get("outcome"),
                                                  r.get("wrapper_success")) != expected for r in records):
            missing.append("unexpected_business_failure")
    receipts = row.get("tool_receipts") or []
    if Counter(m.get("tool_call_id") for m in receipts) != Counter(c.get("id") for c in calls):
        missing.append("state_tool_receipts")
    for bridge in result["scenario_proof"]:
        identifier = bridge["tool_call_id"]
        local = [m for m in receipts if m.get("tool_call_id") == identifier]
        cloud = [m for m in objects(decoded(by_id[bridge["response_generation"]].get("input")))
                 if m.get("tool_call_id") == identifier and "content" in m]
        if (len(local) != 1 or len(cloud) != 1
                or decoded(local[0].get("content")) != decoded(cloud[0].get("content"))
                or cloud[0].get("status", local[0].get("status")) != local[0].get("status")):
            missing.append("cloud_state_receipt:" + str(identifier))
    final = row.get("final_answer")
    digest = content_digest(final) if final else None
    final_generations = [g for g in generations if final and any(
        item.get("content") == final and not item.get("tool_calls") for item in objects(decoded(g.get("output"))))]
    latest_end = max((timestamp(g.get("endTime")) or 0 for g in generations), default=0)
    if len(final_generations) != 1 or timestamp(final_generations[0].get("endTime")) != latest_end:
        missing.append("cloud_final_answer")
    review = row.get("diagnosis_review") or {}
    if (digest and review.get("answer_sha256") == digest and review.get("source")
            and review.get("status") in {"PASS", "FAIL"}):
        result["diagnosis_behavior"] = review["status"]
    if result["diagnosis_behavior"] != "PASS":
        missing.append("diagnosis_behavior_review")
    if row.get("scenario_id") == "S08":
        signatures = Counter(signature(c.get("name"), c.get("args")) for c in calls)
        result["event_result"] = "TRIGGERED" if any(n > 1 for n in signatures.values()) else "NOT_TRIGGERED"
    if row.get("scenario_id") == "S07":
        from obs_lab_faults import retry_recovered

        attempts = row.get("model_attempts") or []
        result["event_result"] = "UNKNOWN" if attempts else "NOT RUN"
        spans = [o for o in selected if o.get("name") == "model_http_attempt" and o.get("type") == "CHAIN"]
        outputs = [decoded(o.get("output")) for o in spans]
        if (not retry_recovered(attempts, row.get("model_decisions", 0)) or len(outputs) != len(attempts)
                or sorted(outputs, key=lambda a: a.get("attempt", 0) if isinstance(a, dict) else 0)
                != attempts):
            missing.append("cloud_attempt_correlation")
        else:
            # Attempts must be descendants of a model decision's llm CHAIN, inside its time window.
            for span in spans:
                parent = by_id.get(span.get("parentObservationId"))
                if not parent or parent.get("name") != "llm" or not any(
                    g.get("parentObservationId") == parent["id"] for g in generations):
                    missing.append("cloud_attempt_parent")
            ordered = sorted(generations, key=lambda g: timestamp(g.get("startTime")) or 0)
            expected_groups = [[1, 2]] + [[i + 2] for i in range(1, len(ordered))]
            for generation, expected_numbers in zip(ordered, expected_groups, strict=True):
                group = [decoded(s.get("output")) for s in spans
                         if s.get("parentObservationId") == generation.get("parentObservationId")]
                if sorted(a.get("attempt", 0) for a in group) != expected_numbers:
                    missing.append("cloud_attempt_decision")
            if not missing:
                result["event_result"] = "RECOVERED"
    result["scenario_missing"] = list(dict.fromkeys(missing))
    result["scenario_observable"] = "BLOCKED" if missing else "PASS"
    if not missing:
        result["status"] = "verified"
    return result
