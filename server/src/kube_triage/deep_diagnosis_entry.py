"""仅供独立 Aegra 实验配置导入，要求显式模型配置。"""

import os

from kube_triage.config import ConfigurationError
from kube_triage.deep_diagnosis import build_graph

if os.getenv("DEEP_DIAGNOSIS_FAKE_MODEL") == "true":
    if os.getenv("TRIAGE_ENV") != "test":
        raise ConfigurationError("FakeModel 只允许 TRIAGE_ENV=test")
    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel

    graph = build_graph(ProtocolFakeModel())
elif os.getenv("DEEP_DIAGNOSIS_ENABLE_PROVIDER") == "true":
    graph = build_graph()
else:
    raise ConfigurationError("Deep Diagnosis Provider 默认关闭；须显式启用实验入口")
