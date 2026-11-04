"""Attach v4 experiment context to the isolated LangGraph trace, using its existing exporter."""

import json

from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.trace import format_span_id


class ExperimentSpans(SpanProcessor):
    def __init__(self, item):
        self.item = item
        self.root = None

    def on_start(self, span, parent_context=None):
        if span.parent is None and span.name == "LangGraph":
            self.root = span
            span.set_attribute("langfuse.observation.input", self.item["question"])
            span.set_attribute("langfuse.experiment.item.expected_output",
                               json.dumps(self.item["expected"], ensure_ascii=False))
        if self.root and span.context.trace_id == self.root.context.trace_id:
            span.set_attributes(self.item["attributes"])
            span.set_attribute("langfuse.experiment.item.root_observation_id",
                               format_span_id(self.root.context.span_id))

    def on_end(self, span):
        if not self.root or span.context.trace_id != self.root.context.trace_id or span.name != "llm":
            return
        # OpenInference serializes LangChain AIMessage as {type, data}; use the final answer
        # only. The runner independently compares it with the saved Aegra state after ingestion.
        try:
            message = json.loads(span.attributes.get("output.value", "{}"))["messages"][-1]
            data = message["data"]
            if message["type"] == "ai" and not data.get("tool_calls") and isinstance(data["content"], str):
                self.root.set_attribute("langfuse.observation.output", data["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            return
