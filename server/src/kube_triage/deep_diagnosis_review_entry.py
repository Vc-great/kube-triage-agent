"""隔离 Reviewer Demo：必须显式启用测试 FakeModel，无 Provider 默认值。"""

import os

from kube_triage.config import ConfigurationError
from kube_triage.deep_diagnosis_review import build_graph
from kube_triage.deep_diagnosis_review_fake import (
    ReviewerProtocolFakeModel,
    ReviewProtocolFakeModel,
)

if os.getenv("TRIAGE_ENV") != "test" or os.getenv("DEEP_DIAGNOSIS_FAKE_MODEL") != "true":
    raise ConfigurationError("Reviewer Demo 只允许 TRIAGE_ENV=test 与显式 FakeModel")

graph = build_graph(ReviewProtocolFakeModel(), ReviewerProtocolFakeModel()).copy(
    update={"config": {"recursion_limit": 100}}
)
