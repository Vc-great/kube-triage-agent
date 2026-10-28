"""Test-only Summary observation adapter; uses the existing callback/exporter chain."""

import contextvars
import json
import logging

from langchain_core.runnables import RunnableLambda

_records = contextvars.ContextVar("obs_lab_summary_records", default=None)


class SummaryAudit(logging.Handler):
    """Copy only the existing safe context audit allowlist, never prompts or state."""

    def emit(self, record):
        target = _records.get()
        if target is None:
            return
        try:
            event = json.loads(record.getMessage())
        except (ValueError, TypeError):
            return
        if event.get("event") == "context_summary":
            target.append({key: event.get(key) for key in (
                "status", "cache_hit", "summary_calls", "input_tokens", "output_tokens",
                "duration_ms", "error_code")})


def observed_summary(original):
    """Wrap only in the isolated lab process; no state/input messages become metadata."""
    async def summary(model, state, schemas, plan, total_budget):
        result = None

        async def invoke(_input):
            nonlocal result
            records = []
            token = _records.set(records)
            try:
                result = await original(model, state, schemas, plan, total_budget)
            finally:
                _records.reset(token)
            return {"context_summary_outcomes": records,
                    "estimated_tokens_before_summary": plan.estimated_tokens,
                    "omitted_rounds": plan.omitted_rounds, "total_budget": total_budget,
                    "source": "existing_graph_context_summary_audit"}

        await RunnableLambda(invoke, name="context_summary_outcome").ainvoke({
            "total_budget": total_budget, "omitted_rounds": plan.omitted_rounds})
        return result
    return summary


def install():
    from kube_triage import graph

    audit = logging.getLogger("kube_triage.audit")
    audit.setLevel(logging.INFO)
    audit.addHandler(SummaryAudit())
    graph._summary_view = observed_summary(graph._summary_view)
