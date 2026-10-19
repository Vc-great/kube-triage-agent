"""B1 Planning 图的隔离 Aegra 入口；真实 Provider 默认关闭。"""

import os

from kube_triage.config import ConfigurationError
from kube_triage.deep_diagnosis_planning import build_graph

if os.getenv("DEEP_DIAGNOSIS_FAKE_MODEL") == "true":
    if os.getenv("TRIAGE_ENV") != "test":
        raise ConfigurationError("FakeModel 只允许 TRIAGE_ENV=test")
    from kube_triage.deep_diagnosis_planning_fake import PlanningProtocolFakeModel

    graph = build_graph(PlanningProtocolFakeModel())
elif os.getenv("DEEP_DIAGNOSIS_ENABLE_PROVIDER") == "true":
    graph = build_graph()
else:
    raise ConfigurationError("Planning Provider 默认关闭；须显式启用实验入口")
