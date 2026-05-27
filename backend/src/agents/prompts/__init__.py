from src.agents.prompts.creative_advisor import CREATIVE_ADVISOR_PROMPT
from src.agents.prompts.general_agent import GENERAL_AGENT_PROMPT
from src.agents.prompts.mindmap_agent import MINDMAP_SYSTEM_PROMPT

__all__ = [
    "CREATIVE_ADVISOR_PROMPT",
    "GENERAL_AGENT_PROMPT",
    "MINDMAP_SYSTEM_PROMPT",
    "get_prompt_for_agent",
]

# Agent 类型 → 系统提示词注册表
# 新增智能体时在此添加映射即可
_AGENT_PROMPTS: dict[str, str] = {
    "default": GENERAL_AGENT_PROMPT,
    "general": GENERAL_AGENT_PROMPT,
    "creative": CREATIVE_ADVISOR_PROMPT,
    "creative_director": CREATIVE_ADVISOR_PROMPT,
    "mindmap": MINDMAP_SYSTEM_PROMPT,
}


def get_prompt_for_agent(agent_type: str) -> str:
    """根据 Agent 类型返回对应的系统提示词。

    未注册的类型返回综合智能体提示词作为兜底。
    新增智能体类型只需在 _AGENT_PROMPTS 字典中添加映射即可。
    """
    return _AGENT_PROMPTS.get(agent_type, GENERAL_AGENT_PROMPT)
