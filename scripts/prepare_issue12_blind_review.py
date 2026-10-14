"""Prepare private, arm-blinded human forms from existing Issue #12 runs only."""

import argparse
import hashlib
import hmac
import json
import os
import secrets
from collections import Counter
from pathlib import Path

from eval_issue12 import (
    FROZEN_DATASET_SHA,
    FROZEN_FIXTURES_SHA,
    FROZEN_PROMPT_SHA,
    ROOT,
    fixtures_sha,
    prompt_sha,
    sha256,
)

FIELDS = ("diagnosis_correct", "grounding_score", "false_positive",
          "causal_overclaim", "tool_error_handling", "reason", "reviewer", "reviewed_at")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def key(item):
    return item["arm"], item["case_id"], item["repeat"]


def index(items, expected):
    if len(items) != 48 or {key(x) for x in items} != expected:
        raise ValueError("Missing or duplicate A/B review records")
    return {key(x): x for x in items}


def final_text(messages):
    finals = [m for m in messages if m.get("type") == "ai" and not m.get("tool_calls")]
    if not finals:
        raise ValueError("Missing final AI answer")
    content = finals[-1]["content"]
    return "".join(part.get("text", "") for part in content) if isinstance(content, list) else content


def prepare(source):
    source = source.resolve()
    if source.parent != (ROOT / ".local/eval-runs").resolve() or not source.is_dir():
        raise ValueError("Source must be an existing private Issue #12 run directory")
    cases_path = ROOT / "eval/issue12/blind-v1.json"
    if (sha256(cases_path) != FROZEN_DATASET_SHA or fixtures_sha() != FROZEN_FIXTURES_SHA or
            any(prompt_sha(arm) != FROZEN_PROMPT_SHA[arm] for arm in "AB")):
        raise ValueError("Frozen input drift")
    cases = {case["id"]: case for case in read_json(cases_path)["cases"]}
    expected = {(arm, case, repeat) for arm in "AB" for case in cases for repeat in (1, 2, 3)}
    runs = index(read_json(source / "runs.json"), expected)
    facts = index(read_json(source / "human-review-facts.json")["items"], expected)
    reviews = index(read_json(source / "reviews.json"), expected)
    summary = read_json(source / "summary.json")
    if (len(cases) != 8 or summary["paired_recorded"] != 24 or
            summary["attempted_total"] != 48 or summary["not_run_total"] != 0 or
            any(reviews[k][field] != "PENDING" or facts[k][field] != "PENDING"
                for k in expected for field in FIELDS)):
        raise ValueError("Run count or human review state changed")
    if (len({r["thread_id"] for r in runs.values()}) != 48 or
            len({r["run_id"] for r in runs.values()}) != 48):
        raise ValueError("Duplicate Thread or Run ID")
    graph_sha = sha256(ROOT / "server/src/kube_triage/graph.py")
    for k, run in runs.items():
        arm, case_id, repeat = k
        if (run["dataset_sha"] != FROZEN_DATASET_SHA or
                run["fixture_bundle_sha"] != FROZEN_FIXTURES_SHA or
                run["prompt_sha"] != FROZEN_PROMPT_SHA[arm] or
                run["graph_sha"] != graph_sha or run["model_name"] != "gpt-6-luna" or
                run["run_status"] != "success" or not run["tool_message_match"]):
            raise ValueError("Run metadata drift")
        trace = read_json(source / f"{arm}-{case_id}-{repeat}-private.json")
        messages = trace["state"]["values"]["messages"]
        tools = [m for m in messages if m.get("type") == "tool"]
        fact = facts[k]
        if (trace["thread_id"] != run["thread_id"] or
                trace["runs"][-1]["run_id"] != run["run_id"] or
                fact["question"] != next(m for m in messages if m.get("type") == "human")["content"] or
                fact["model_answer"] != final_text(messages) or
                fact["tool_message_ids"] != [m["tool_call_id"] for m in tools] or
                [e["content"] for e in fact["model_seen_evidence"]] != [m["content"] for m in tools] or
                fact["independent_ground_truth"] != cases[case_id]["ground_truth"]):
            raise ValueError("Raw trace and review facts disagree")
    seed = secrets.token_bytes(32)
    def digest(k):
        return hmac.new(seed, json.dumps(k).encode(), hashlib.sha256).hexdigest()
    ordered = sorted(expected, key=digest)
    forms = []
    mapping = []
    for k in ordered:
        arm, case_id, repeat = k
        fact, run, case = facts[k], runs[k], cases[case_id]
        review_id = "R-" + digest(k)[:16]
        forms.append({
            "review_id": review_id, "question": fact["question"],
            "answer": fact["model_answer"], "tool_message_ids": fact["tool_message_ids"],
            "model_seen_evidence": fact["model_seen_evidence"],
            "independent_ground_truth": fact["independent_ground_truth"],
            "forbidden_claims": case["forbidden_claims"],
            **{field: "PENDING" for field in FIELDS},
        })
        mapping.append({"review_id": review_id, "arm": arm, "case_id": case_id,
                        "repeat": repeat, "thread_id": run["thread_id"],
                        "run_id": run["run_id"],
                        "private_trace_file": f"{arm}-{case_id}-{repeat}-private.json"})
    if len({item["review_id"] for item in forms}) != 48:
        raise ValueError("Review ID collision")
    review_dir = source / "review"
    review_dir.mkdir(mode=0o700, exist_ok=False)
    os.chmod(review_dir, 0o700)
    def save(name, value):
        path = review_dir / name
        with path.open("x", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    save("blind-review-forms.json", forms)
    save("blind-id-map.json", {"seed_hex": seed.hex(), "mapping": mapping})
    save("source-manifest.json", {name: sha256(source / name) for name in
                                  ("runs.json", "summary.json", "reviews.json",
                                   "human-review-facts.json")})
    handoff = review_dir / "review-handoff.md"
    with handoff.open("x", encoding="utf-8") as stream:
        os.chmod(handoff, 0o600)
        stream.write("# Issue #12 人工盲审交接\n\n"
                     "本包有 48 条真实回答，按不透明 review_id 打乱。请只打开 blind-review-forms.json；"
                     "blind-id-map.json 含 A/B 映射，仅解盲汇总时使用。"
                     "盲法仅隐藏 A/B；题目、Ground Truth、禁止断言对审阅者可见。\n\n"
                     "逐条阅读完整 answer、model_seen_evidence 与 independent_ground_truth。"
                     "ToolMessage ID 必须在理由中引用，且不要将独立 Ground Truth 当作模型当时所见。"
                     "Event UID 相等才是目标强证据；缺 UID 为弱线索，明确冲突则不是目标证据。\n\n"
                     "填写 diagnosis_correct：正确 1，错误 0；grounding_score：无依据/矛盾 0，"
                     "部分依据 1，关键结论有充分依据 2；false_positive：有健康样本误报 1，否则 0；"
                     "causal_overclaim：有越证据因果断言 1，否则 0；tool_error_handling："
                     "发生工具错误且处理妥当 1、处理不当 0、没有相关错误 NA。"
                     "请在 reason 写具体证据、禁止断言核对结果与对应 ToolMessage ID，"
                     "并填写 reviewer、reviewed_at（ISO 8601 时间）。\n\n"
                     "仅将本人已核实的字段从 PENDING 改为有效值，另存评分副本，"
                     "勿覆盖本包、runs.json、summary.json、reviews.json 或原始轨迹。"
                     "未完成的条目保持 PENDING；全部 48 条经本人确认后，"
                     "再交回评分副本进行离线校验与解盲。不得把本包提交到 Git 或外部服务。\n")
    print(json.dumps({"review_dir": str(review_dir), "forms": len(forms),
                      "pairs": len(Counter((x["case_id"], x["repeat"]) for x in mapping))},
                     ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
