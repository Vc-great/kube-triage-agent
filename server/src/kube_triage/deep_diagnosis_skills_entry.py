"""隔离 Skills Demo 入口；V2 本期仅 FakeModel，不启用付费 Provider。"""

import os

from kube_triage.config import ConfigurationError
from kube_triage.deep_diagnosis_skills import build_graph
from kube_triage.deep_diagnosis_skills_fake import SkillsProtocolFakeModel

if os.getenv("TRIAGE_ENV") != "test" or os.getenv("DEEP_DIAGNOSIS_FAKE_MODEL") != "true":
    raise ConfigurationError("Skills V2 Demo 只允许 TRIAGE_ENV=test 与显式 FakeModel")

graph = build_graph(SkillsProtocolFakeModel())
