"""
Harness Agent — AI 自进化的 Meta Agent。

Harness Agent 是一个特殊的 Agent，专门用于：
1. 理解用户的 Skill 需求
2. 搜索已有 Skill 避免重复
3. 生成 Skill 代码
4. 沙箱测试 + 安全扫描
5. 注册/安装 Skill

它使用专门的工具集（skill_tools）和专门的系统提示词，
引导 LLM 按标准的 Harness Engineering 流程操作。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from src.agents.base import BaseAgent
from src.agents.tools.skill_tools import (
    GenerateSkillCodeTool,
    InstallSkillTool,
    RegisterSkillTool,
    ScanSkillTool,
    SearchSkillsTool,
    TestSkillTool,
)
from src.harness.tool_registry import register_tool

# Harness Agent 系统提示词
HARNESS_SYSTEM_PROMPT = """你是一个 **Harness Engineering Agent** — 专门负责为 AI 平台创建和安装新的能力 (Skill)。

## 你的职责
1. 理解用户对 Skill 的需求
2. 搜索已有的 Skill，避免重复造轮子
3. 生成安全的 Python Skill 代码
4. 在沙箱中测试 Skill
5. 安全扫描 → 注册 → 激活

## 可用工具
- `search_skills` — 搜索已有 Skill，创建前**必须**先检查
- `generate_skill_code` — 生成 Skill 代码模板
- `test_skill` — 在沙箱中测试
- `scan_skill` — 安全扫描
- `register_skill` — 注册到系统
- `install_skill` — 一键安装（推荐）

## Skill 代码规范
生成的 Python 代码必须遵循以下格式：

```python
\"\"\"Skill: name — 简短描述\"\"\"
import json
from typing import Any

def execute(input_data: dict[str, Any]) -> dict[str, Any]:
    \"\"\"核心函数，input_data 是用户提供的参数。\"\"\"
    # 实现逻辑
    return {"success": True, "result": "..."}
```

### 安全规则
- ✅ 允许: json, math, datetime, collections, typing, re, httpx, requests
- ❌ 禁止: os, subprocess, sys, eval, exec, open, __import__, socket, ctypes
- 必须定义 execute(input_data) 函数
- 返回值必须是 dict，至少包含 "success" (bool) 字段

## 工作流程
1. 接收用户需求 → `search_skills` 检查重复
2. 生成代码 → `install_skill` 一键完成测试+扫描+安装
3. 如果 `install_skill` 失败 → 分析失败原因 → 修复代码 → 重试
4. 安装成功后告诉用户 Skill 名称

## 输出规范
- 代码放在 Markdown 代码块中
- 失败时分析原因并给出修复建议
- 成功后列出 Skill 的名称、用途和调用方式
"""


def create_harness_agent(llm: BaseChatModel) -> BaseAgent:
    """
    创建 Harness Agent 实例。

    Args:
        llm: LLM 实例

    Returns:
        配置好的 Harness Agent
    """
    # 注册 Skill 工具到 HarnessTool 注册表
    skill_tools = [
        SearchSkillsTool(),
        GenerateSkillCodeTool(),
        TestSkillTool(),
        ScanSkillTool(),
        RegisterSkillTool(),
        InstallSkillTool(),
    ]
    for tool in skill_tools:
        register_tool(tool)

    # 转为 LangChain tools
    lc_tools = [t.to_langchain_tool() for t in skill_tools]

    agent = BaseAgent(
        llm=llm,
        tools=lc_tools,
        system_prompt=HARNESS_SYSTEM_PROMPT,
        enable_planning=True,  # Plan+ReAct 双模型
    )

    return agent


async def run_harness_agent(
    llm: BaseChatModel,
    user_request: str,
    thread_id: str = "harness-default",
) -> dict[str, Any]:
    """
    便捷函数：运行 Harness Agent 处理 Skill 创建请求。

    Args:
        llm: LLM 实例
        user_request: 用户对 Skill 的需求描述
        thread_id: 会话 ID

    Returns:
        执行结果字典
    """
    agent = create_harness_agent(llm)
    return await agent.run(
        user_input=user_request,
        metadata={
            "thread_id": thread_id,
            "agent_type": "harness",
            "tags": ["harness", "skill-generation"],
        },
    )
