"""Phase C scenario contracts. Offline helpers never call a Provider or Cloud."""

from obs_lab_scores import frozen_cases

SUMMARY_BUDGET = 7200
SUMMARY_MAX_TURNS = 10


def summary_question(turn):
    if type(turn) is not int or not 1 <= turn <= SUMMARY_MAX_TURNS:
        raise ValueError("S09 turn budget exceeded")
    return (f"合成实验第{turn}轮：只读检查 kube-triage-demo 中 sample-h 当前状态，"
            "取得当前证据，保留未知事项，不执行修复。"
            "以下是为上下文实验创建的历史背景材料，不是当前证据："
            + "学习者希望理解历史参考与当前Pod状态的区别。" * 12)


def grounding_case():
    """Keep the trusted answer out of the model question; refuse changed truth/fixtures."""
    return frozen_cases()["g"]


def grounding_question():
    return grounding_case()["question"]


def context_environments(environment):
    return {**environment, "CONTEXT_WINDOW_ENABLED": "true", "CONTEXT_SUMMARY_ENABLED": "true",
            "CONTEXT_ESTIMATED_TOTAL_BUDGET": str(SUMMARY_BUDGET)}
