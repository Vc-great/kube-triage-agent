"""Phase A 独立 Aegra 入口：只支持显式 test/Fake，不启用 Provider。"""

import os

from kube_triage.config import ConfigurationError
from kube_triage.deep_diagnosis_offload import build_graph
from kube_triage.deep_diagnosis_offload_fake import NotesProtocolFakeModel

if os.getenv("TRIAGE_ENV") != "test" or os.getenv("DEEP_DIAGNOSIS_FAKE_MODEL") != "true":
    raise ConfigurationError("虚拟笔记 Demo 只允许 TRIAGE_ENV=test 与显式 FakeModel")

graph = build_graph(NotesProtocolFakeModel()).copy(update={"config": {"recursion_limit": 100}})
