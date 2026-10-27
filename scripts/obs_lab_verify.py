"""Pure Phase A evidence validation: existence is separate from a proven chain."""

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


def verify_cloud(observations, row, project):
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
    result["chain_verified"] = not missing
    if not missing:
        result.update(chain_status="PASS", timeline_status="PASS", tool_call_id_status="PASS")
    return result
