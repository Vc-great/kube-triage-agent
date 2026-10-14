"""Read existing private evaluation trajectories and derive offline metrics v1."""

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_HOME = (ROOT.parents[2] if ROOT.parent.name == "worktrees" and
                ROOT.parent.parent.name == ".local" else ROOT)
METRICS_ROOT = ROOT / ".local/eval-metrics"
TOKEN_KEYS = {"input": ("input_tokens", "prompt_tokens"),
              "output": ("output_tokens", "completion_tokens"),
              "total": ("total_tokens",)}


def metric(value, unit, denominator, provenance, reason=None, status="observed"):
    return {"value": value, "unit": unit, "denominator": denominator,
            "provenance": provenance, "status": status if value is not None else "unknown",
            "reason": reason if value is None else None}


def value(item):
    return item["value"]


def number(data, aliases):
    for key in aliases:
        value = data.get(key)
        if type(value) is int and value >= 0:
            return value, key
    return None, None


def usage_message(message):
    primary = message.get("usage_metadata")
    fallback = (message.get("response_metadata") or {}).get("token_usage")
    data, source = (primary, "usage_metadata") if isinstance(primary, dict) else (
        (fallback, "response_metadata.token_usage") if isinstance(fallback, dict) else (None, None))
    if data is None:
        return {key: metric(None, "tokens", "one model reply", "provider", "usage_missing")
                for key in TOKEN_KEYS} | {"details": {}, "inconsistent": False}
    fields = {}
    for key, aliases in TOKEN_KEYS.items():
        value, alias = number(data, aliases)
        fields[key] = metric(value, "tokens", "one model reply",
                             f"{source}.{alias}" if alias else source,
                             "field_missing_or_invalid" if alias is None else None)
    if fields["total"]["value"] is None and all(fields[key]["value"] is not None
                                                  for key in ("input", "output")):
        fields["total"] = metric(fields["input"]["value"] + fields["output"]["value"],
                                 "tokens", "one model reply", "input+output", status="derived")
    inconsistent = all(fields[key]["value"] is not None for key in TOKEN_KEYS) and (
        fields["input"]["value"] + fields["output"]["value"] != fields["total"]["value"])
    details = {}
    for parent, keys in (("input_token_details", ("cache_read", "cached_tokens")),
                         ("prompt_tokens_details", ("cached_tokens",)),
                         ("output_token_details", ("reasoning", "reasoning_tokens")),
                         ("completion_tokens_details", ("reasoning_tokens",))):
        container = data.get(parent)
        if not isinstance(container, dict) and isinstance(fallback, dict):
            container = fallback.get(parent)
        if isinstance(container, dict):
            for key in keys:
                value, _ = number(container, (key,))
                if value is not None:
                    details[f"{parent}.{key}"] = metric(value, "tokens", "one model reply",
                                                          f"{source}.{parent}.{key}")
    return fields | {"details": details, "inconsistent": inconsistent}


def model_messages(messages):
    seen = {}
    replies = []
    reasons = []
    for message in messages:
        if message.get("type", message.get("role", "")).lower() not in {"ai", "assistant"}:
            continue
        if message.get("name") != "triage_llm":
            continue  # Graph fallback AIMessage is not a paid model reply.
        ident = message.get("id")
        if not isinstance(ident, str) or not ident:
            reasons.append("model_message_id_missing")
            continue
        if ident in seen:
            if seen[ident] != message:
                reasons.append("model_message_id_conflict")
            continue
        seen[ident] = message
        replies.append(usage_message(message))
    sums = {}
    inconsistent = any(reply["inconsistent"] for reply in replies)
    for key in TOKEN_KEYS:
        values = [reply[key]["value"] for reply in replies]
        complete = bool(replies) and len(values) == len(replies) and all(
            value is not None for value in values) and not reasons and not inconsistent
        sums[key] = metric(sum(values) if complete else None, "tokens", len(replies),
                           "final_state.unique_triage_llm_messages",
                           None if complete else "incomplete_or_inconsistent_model_usage",
                           "derived")
    return {"observed_decisions": metric(len(replies), "messages", "final state",
                                           "message.name=triage_llm"),
            "replies": replies, "totals": sums,
            "complete": all(sums[key]["value"] is not None for key in TOKEN_KEYS),
            "missing_reasons": sorted(set(reasons))}


def structural_validity(result):
    if isinstance(result, (dict, list)):
        return "VALID"
    if not isinstance(result, str) or not result.strip():
        return "INVALID"
    try:
        parsed = json.loads(result)
    except ValueError:
        try:
            import yaml
            parsed = yaml.safe_load(result)
        except (ImportError, ValueError):
            return "INVALID" if result.lstrip().startswith(("{", "[")) else "UNVERIFIED"
        except yaml.YAMLError:
            return "INVALID"
    return "VALID" if isinstance(parsed, (dict, list)) else "UNVERIFIED"


def tool_metrics(messages):
    calls = [call for m in messages if m.get("type", m.get("role", "")).lower() in
             {"ai", "assistant"} for call in m.get("tool_calls", []) if isinstance(call, dict)]
    responses = [m for m in messages if m.get("type", m.get("role", "")).lower() == "tool"]
    call_ids = Counter(c.get("id") for c in calls if isinstance(c.get("id"), str) and c["id"])
    msg_ids = Counter(m.get("tool_call_id") for m in responses
                      if isinstance(m.get("tool_call_id"), str) and m["tool_call_id"])
    paired = {key for key in call_ids if call_ids[key] == msg_ids[key] == 1}
    counts = Counter()
    validity = Counter()
    for response in responses:
        if response.get("tool_call_id") not in paired:
            continue
        try:
            payload = json.loads(response.get("content", ""))
        except (TypeError, ValueError):
            payload = None
        outer = response.get("status")
        ok = payload.get("ok") if isinstance(payload, dict) else None
        error_type = payload.get("error_type") if isinstance(payload, dict) else None
        if error_type == "policy" and ok is False:
            kind = "policy_rejected"
        elif error_type == "budget" and ok is False:
            kind = "budget_skipped"
        elif outer == "success" and ok is True:
            kind = "wrapper_success"
            validity[structural_validity(payload.get("result"))] += 1
        elif ok is False:
            kind = "wrapper_error"
        else:
            kind = "unknown"
        if outer == "error" and ok is True:
            kind = "unknown"
        counts[kind] += 1
    unknown_or_unpaired = len(calls) + len(responses) - 2 * len(paired)
    result = {"tool_requests": metric(len(calls), "calls", "final state", "AIMessage.tool_calls"),
              "tool_messages_received": metric(len(responses), "messages", "final state",
                                                "ToolMessage"),
              "matched_tool_responses": metric(len(paired), "messages", "unique call IDs",
                                               "ID one-to-one match"),
              "unknown_or_unpaired": metric(unknown_or_unpaired, "records", "calls+messages",
                                             "ID pairing"),
              "mcp_transport_attempts": metric(None, "attempts", None, "server trace",
                                               "tool_call_id_trace_missing")}
    for key in ("wrapper_success", "wrapper_error", "policy_rejected", "budget_skipped", "unknown"):
        result[key] = metric(counts[key], "messages", len(paired), "paired ToolMessage envelope")
    for key in ("VALID", "INVALID", "UNVERIFIED"):
        result[f"content_{key.lower()}"] = metric(validity[key], "messages",
            counts["wrapper_success"], "conservative native result parser")
    result["tool_failure_detected"] = bool(counts["wrapper_error"] or counts["policy_rejected"] or
                                           counts["budget_skipped"] or counts["unknown"] or
                                           unknown_or_unpaired or validity["INVALID"])
    return result


def latency(values):
    ordered = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v) and v >= 0)
    n = len(ordered)
    return {"n": metric(n, "runs", len(values), "observed elapsed_seconds"),
            "p50": metric(statistics.median(ordered) if n else None, "seconds", n,
                                   "runner.elapsed_seconds; statistics.median", "no_observations"),
            "p95": metric(ordered[math.ceil(.95 * n) - 1] if n else None, "seconds", n,
                           "runner.elapsed_seconds; nearest_rank", "no_observations"),
            "warning": "LOW_SAMPLE_WARNING" if n < 20 else None,
            "missing_count": metric(len(values) - n, "runs", len(values),
                                    "missing or invalid elapsed_seconds")}


def estimated_cost(tokens, details, snapshot, row):
    unknown = metric(None, snapshot.get("currency") if isinstance(snapshot, dict) else None,
                     "one run", "price snapshot", "price_or_usage_unverified")
    if not isinstance(snapshot, dict) or snapshot.get("classification") == "FICTIONAL_EXAMPLE":
        return unknown
    required = ("provider", "billing_entity", "model_deployment", "currency", "unit",
                "input_uncached_rate", "input_cached_rate", "output_rate", "effective_at",
                "source_checked_at", "source_url_or_document", "assumptions")
    if any(snapshot.get(key) is None for key in required) or snapshot["unit"] != "per_1m_tokens":
        return unknown
    if snapshot["provider"] != row.get("provider") or snapshot["model_deployment"] != row.get(
            "model_deployment", row.get("model_name")) or snapshot["currency"] != row.get("currency"):
        return unknown
    if any(not isinstance(snapshot[key], str) or not snapshot[key].strip() for key in (
            "provider", "billing_entity", "model_deployment", "currency",
            "source_url_or_document", "assumptions")):
        return unknown
    if not row.get("provider_verified") or row.get("hidden_retries_unknown", True):
        return unknown
    try:
        effective = datetime.fromisoformat(snapshot["effective_at"])
        datetime.fromisoformat(snapshot["source_checked_at"])
        run_at = datetime.fromisoformat(row["run_at"])
        end = snapshot.get("effective_until")
        if run_at < effective or (end and run_at >= datetime.fromisoformat(end)):
            return unknown
        rates = [Decimal(str(snapshot[key])) for key in required if key.endswith("_rate")]
        if any(rate < 0 for rate in rates):
            return unknown
    except (ValueError, TypeError, InvalidOperation, KeyError):
        return unknown
    if not all(tokens[key]["value"] is not None for key in ("input", "output")):
        return unknown
    cache = [item["value"] for key, item in details.items() if key.endswith(
        ("cache_read", "cached_tokens")) and key.startswith(("input", "prompt"))]
    if rates[0] != rates[1] and len(cache) != 1:
        return unknown
    cached = cache[0] if cache else 0
    if cached > tokens["input"]["value"]:
        return unknown
    amount = ((Decimal(tokens["input"]["value"] - cached) * rates[0]) +
              (Decimal(cached) * rates[1]) +
              (Decimal(tokens["output"]["value"]) * rates[2])) / Decimal(1_000_000)
    return metric(str(amount), snapshot["currency"], "one run",
                  "verified provider price snapshot + complete usage", status="estimated")


def normalize(row, evidence, dataset, snapshot=None):
    issue12 = dataset == "issue12-blind-v1"
    state = evidence.get("state") if issue12 and isinstance(evidence, dict) else None
    messages = (state.get("values", {}).get("messages") if isinstance(state, dict) else
                evidence.get("messages") if isinstance(evidence, dict) else None)
    reasons = []
    if not isinstance(messages, list):
        messages = []
        reasons.append("final_state_missing")
    models = model_messages(messages)
    if "final_state_missing" in reasons:
        models["observed_decisions"] = metric(None, "messages", None, "final state",
                                              "final_state_missing")
    tools = tool_metrics(messages) if not reasons else None
    reasons.extend(models["missing_reasons"])
    if not models["complete"]:
        reasons.append("usage_incomplete")
    if tools is None:
        reasons.append("tool_metrics_unknown")
    model_id = row.get("model_name")
    observed = row.get("observed_model_names")
    if isinstance(observed, list) and len(observed) == 1:
        model_id, model_origin = observed[0], "response_metadata"
    else:
        model_origin = "configured" if model_id else "unknown"
    duration = row.get("elapsed_seconds")
    if type(duration) not in (float, int) or duration < 0 or not math.isfinite(duration):
        duration = None
        reasons.append("elapsed_seconds_missing")
    detail_keys = {key for reply in models["replies"] for key in reply["details"]}
    details = {}
    for key in detail_keys:
        values = [reply["details"][key]["value"] for reply in models["replies"]
                  if key in reply["details"]]
        if len(values) == len(models["replies"]) and values:
            details[key] = metric(sum(values), "tokens", len(values),
                                  f"sum of {key} across model replies", status="derived")
    cost = estimated_cost(models["totals"], details, snapshot, row)
    return {"schema": "metrics-v1", "dataset": dataset, "version": dataset,
            "source_type": "issue12_mock" if issue12 else "phase3a_mock",
            "source_sha": row.get("dataset_sha"), "case_id": row.get("case_id"),
            "repeat": row.get("repeat"), "arm": row.get("arm") if issue12 else None,
            "model_id": model_id, "model_id_provenance": model_origin,
            "git_sha": row.get("git_sha"), "prompt_sha": row.get("prompt_sha"),
            "thread_id": row.get("thread_id") if row.get("thread_id") not in (None, "UNKNOWN", "NOT RUN") else None,
            "run_id": row.get("run_id") if row.get("run_id") not in (None, "UNKNOWN", "NOT RUN") else None,
            "run_status": row.get("run_status"), "protocol_status": row.get("aegra_run_status"),
            "source_record_present": True, "source_measurement_present": bool(messages),
            "llm": models | {"detail_totals": details}, "tools": tools,
            "run_latency": metric(duration, "seconds", "one runner run",
                                  "time.monotonic runner interval incl. state/history retrieval",
                                  "elapsed_seconds_missing"),
            "model_latency": metric(None, "seconds", None, "model trace", "timestamps_missing"),
            "mcp_latency": metric(None, "seconds", None, "tool_call_id trace", "timestamps_missing"),
            "estimated_cost": cost,
            "actual_billed_cost": metric(None, cost["unit"], "one run", "provider invoice",
                                         "invoice_missing"),
            "diagnosis_correct": metric(None, "boolean", "human reviewed run", "human review",
                                        "not_joined_or_unverified"),
            "missing_reasons": sorted(set(reasons))}


def summarize(records):
    groups = {}
    for name in sorted({"phase3a_mock" if r["source_type"] == "phase3a_mock" else
                        f"issue12_{r['arm']}" for r in records}):
        group = [r for r in records if ("phase3a_mock" if r["source_type"] == "phase3a_mock"
                                       else f"issue12_{r['arm']}") == name]
        token_values = [r["llm"]["totals"]["total"]["value"] for r in group]
        complete = sum(r["llm"]["complete"] for r in group)
        cache = [r["llm"]["detail_totals"].get("input_token_details.cache_read") for r in group]
        reasoning = [r["llm"]["detail_totals"].get("output_token_details.reasoning")
                     for r in group]
        tools = [r["tools"] for r in group if r["tools"] is not None]
        counts = {key: sum(t[key]["value"] for t in tools) for key in (
            "tool_requests", "tool_messages_received", "matched_tool_responses",
            "unknown_or_unpaired", "wrapper_success", "wrapper_error", "policy_rejected",
            "budget_skipped", "unknown", "content_invalid", "content_unverified")}
        def rate(numerator, denominator, values=counts):
            return metric(values[numerator] / values[denominator] if values[denominator] else None,
                          "ratio", values[denominator], f"{numerator}/{denominator}",
                          "zero_denominator")
        durations = [r["run_latency"]["value"] for r in group]
        groups[name] = {"run_count": metric(len(group), "runs", len(group), "source records"),
                        "run_count_with_complete_usage": metric(complete, "runs", len(group),
                                                                "complete final-state usage"),
                        "unknown_count": metric(len(group) - complete, "runs", len(group),
                                                "incomplete final-state usage"),
                        "known_token_sum": metric(sum(v for v in token_values if v is not None),
                                                   "tokens", sum(v is not None for v in token_values),
                                                   "runs with known total_tokens"),
                        "estimated_or_partial": complete != len(group),
                        "all_run_exact_total": metric(
                            sum(token_values) if complete == len(group) else None,
                            "tokens", len(group), "complete final-state usage", "partial_usage"),
                        "cache_read_known_runs": metric(sum(v is not None for v in cache),
                                                        "runs", len(group), "cache detail coverage"),
                        "cache_read_known_sum": metric(sum(v["value"] for v in cache if v),
                                                       "tokens", sum(v is not None for v in cache),
                                                       "input_token_details.cache_read"),
                        "reasoning_known_runs": metric(sum(v is not None for v in reasoning),
                                                       "runs", len(group), "reasoning detail coverage"),
                        "reasoning_known_sum": metric(sum(v["value"] for v in reasoning if v),
                                                      "tokens", sum(v is not None for v in reasoning),
                                                      "output_token_details.reasoning"),
                        "tool_counts": {key: metric(count, "records", len(tools),
                                                    f"sum of per-run {key}")
                                        for key, count in counts.items()},
                        "rates": {"policy_rejected_per_request": rate("policy_rejected", "tool_requests"),
                                  "budget_skipped_per_request": rate("budget_skipped", "tool_requests"),
                                  "wrapper_error_per_matched_response": rate(
                                      "wrapper_error", "matched_tool_responses")},
                        "latency": {"all": latency(durations),
                                    "success": latency([r["run_latency"]["value"] for r in group
                                                        if r["run_status"] == "success"]),
                                    "failure": latency([r["run_latency"]["value"] for r in group
                                                        if r["run_status"] != "success"])},
                        "cost_estimate_known_count": metric(
                            sum(r["estimated_cost"]["value"] is not None for r in group),
                            "runs", len(group), "estimated_cost coverage")}
    return groups


def checked_paths(source, out):
    source, out = source.absolute(), out.absolute()
    if ".." in source.parts or ".." in out.parts:
        raise ValueError("path traversal denied")
    for path in (source, out, *source.parents, *out.parents):
        if path.is_symlink():
            raise ValueError("symlink path denied")
    if source.name.startswith(".") or source.parent.name != "eval-runs" or not source.is_dir():
        raise ValueError("source must be an existing .local/eval-runs/<run-directory>")
    if (source.parent.parent.name != ".local" or source.stat().st_uid != os.getuid() or
            source.stat().st_mode & 0o077):
        raise ValueError("source ownership/layout invalid")
    if not source.is_relative_to(PROJECT_HOME):
        raise ValueError("source outside project checkouts")
    if out.parent != METRICS_ROOT or not out.name.startswith("issue14-"):
        raise ValueError("out must be .local/eval-metrics/issue14-<new-id>")
    if out.exists():
        raise ValueError("out already exists")
    if source == out or source in out.parents or out in source.parents:
        raise ValueError("source/output overlap")
    return source, out


def read_json(path):
    if (path.is_symlink() or path.stat().st_uid != os.getuid() or
            path.stat().st_mode & 0o077 or path.stat().st_size > 32_000_000):
        raise ValueError("unsafe input file")
    return json.loads(path.read_text(encoding="utf-8"))


def report_text(groups, count):
    lines = ["# Issue #14 离线 Metrics v1（脱敏汇总）", "", f"记录数：{count}；真实 Kubernetes：NOT RUN / NO METRICS。",
             "", "Runner 耗时包括 Thread、Run、SSE 与 State/History 取证；P50=median，P95=nearest-rank。",
             "成本仅为估算；无可核验报价或完整 usage 时 UNKNOWN。小样本分位数仅供描述，不是生产 SLO。", ""]
    for name, group in groups.items():
        all_latency = group["latency"]["all"]
        counts = {key: value(item) for key, item in group["tool_counts"].items()}
        lines += [f"## {name}", "", (f"Run：{value(group['run_count'])}；"
                  f"完整 Token：{value(group['run_count_with_complete_usage'])}；"
                  f"未知：{value(group['unknown_count'])}；"
                  f"已知 Token 和：{value(group['known_token_sum'])}。"),
                  (f"P50/P95 秒：{all_latency['p50']['value']} / {all_latency['p95']['value']} "
                  f"(n={value(all_latency['n'])}, {all_latency['warning'] or '描述性'})。"),
                  f"工具计数：{json.dumps(counts, ensure_ascii=False, sort_keys=True)}",
                  (f"成本估算可得：{value(group['cost_estimate_known_count'])}/"
                   f"{value(group['run_count'])}；实际账单 UNKNOWN。"), ""]
        lines += [(f"缓存读取 Token：{value(group['cache_read_known_sum'])}，覆盖 "
                  f"{value(group['cache_read_known_runs'])}/{value(group['run_count'])} Run；"
                  f"推理 Token 细分：{value(group['reasoning_known_sum'])}，覆盖 "
                  f"{value(group['reasoning_known_runs'])}/{value(group['run_count'])} Run。"
                  "细分量不再加到总量。"), ""]
    lines += [("安全残余：Issue #13 G03 PARTIAL FAIL；L3 真实模型对抗 NOT RUN。"
              "包装成功、结构有效、诊断正确分别记录，不互相替代。"), ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", choices=("phase3a-baseline", "issue12-blind-v1"), required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--price-snapshot", type=Path)
    args = parser.parse_args(argv)
    if args.out is None and not args.dry_run:
        parser.error("--out required for analysis")
    out = args.out or METRICS_ROOT / "issue14-dry-run"
    try:
        source, out = checked_paths(args.source, out)
        rows_path = source / "runs.json"
        if not rows_path.is_file() or rows_path.is_symlink():
            raise ValueError("runs.json missing or unsafe")
        rows = read_json(rows_path)
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("invalid runs.json")
        if args.dry_run:
            print(json.dumps({"status": "DRY RUN; NO WRITE; NO NETWORK", "dataset": args.dataset,
                              "source": str(source), "out": str(out), "estimated_records": len(rows),
                              "protection": "new output only; source read-only"}, ensure_ascii=False))
            return 0
        snapshot = read_json(args.price_snapshot) if args.price_snapshot else None
        records = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("invalid run record")
            case, repeat, arm = row.get("case_id"), row.get("repeat"), row.get("arm")
            if not isinstance(case, str) or not case.isalnum() or type(repeat) is not int:
                raise ValueError("invalid case/repeat")
            if args.dataset == "issue12-blind-v1":
                if arm not in ("A", "B"):
                    raise ValueError("invalid arm")
                path = source / f"{arm}-{case}-{repeat}-private.json"
            else:
                path = source / f"{case}-{repeat}-evidence.json"
            evidence = read_json(path) if path.is_file() else {}
            records.append(normalize(row, evidence, args.dataset, snapshot))
        groups = summarize(records)
        os.umask(0o077)
        METRICS_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        METRICS_ROOT.chmod(0o700)
        out.mkdir(mode=0o700)
        for name, content in (("metrics.json", json.dumps({"schema": "metrics-v1", "runs": records,
                              "groups": groups}, ensure_ascii=False, indent=2)),
                              ("report.md", report_text(groups, len(records)))):
            fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content + "\n")
        print(json.dumps({"status": "COMPLETE", "records": len(records), "out": str(out)},
                         ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
