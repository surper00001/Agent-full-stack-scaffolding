# Harness-RAG-Agent 集成分析报告

> 日期: 2026-06-05 | 综合健康评分: **4.7/10**

## 1. 执行摘要

该平台拥有坚实的概念基础——三子系统架构（Harness、RAG、Agent），精心设计的领域（`ProcessSandbox`、`SandboxManager`、`RetrievalPipeline`、`StreamingToolExecutor`），以及明确的安全关注点。然而，**三个子系统之间实际上没有集成**。RAG 独立运行，其 LangChain `@tool` 未注册到 Harness，且完全没有使用沙箱、`AbortSignal` 或 Harness 的安全层。沙箱池管理器设计与预期一致，但每个调用现场都创建新实例，完全绕过了池化。工具注册表、调度和上下文管理等功能已部分实现，因关键连接缺失而无法运行。代码库需要在**系统集成**方面投入重大工程精力，而不是新增功能。

## 2. 当前状态评分

| 维度 | 得分 | 评价 |
|------|------|------|
| 概念架构 | 8/10 | 边界和抽象定义得当 |
| 实现完整性 | 5/10 | 许多功能已启动但未完成 |
| 子系统集成 | **2/10** | Harness / RAG / Agent 各自为政 |
| 代码质量 | 7/10 | Pydantic + LangGraph 运用得当 |
| 测试覆盖率 | 3/10 | 未见广泛的测试基础设施 |
| 生产就绪度 | 3/10 | 存在死代码、未使用的单例和存根 |

## 3. 当前架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer (FastAPI)                       │
│  auth │ agents │ conversations │ skills │ knowledge-bases │ ... │
└──────────┬──────────┬──────────┬──────────┬────────────────────┘
           │          │          │          │
    ┌──────▼──┐ ┌─────▼───┐ ┌───▼────┐ ┌──▼──────────────┐
    │ AuthSvc │ │AgentSvc │ │ConvSvc │ │KnowledgeBaseSvc │
    └─────────┘ └────┬────┘ └───┬────┘ └──┬──────────────┘
                     │           │          │
              ┌──────▼───────────▼──────────▼──────┐
              │         BaseAgent (graph.py)        │
              │  ┌────────────────────────────┐     │
              │  │ Tool Node: dual dispatch   │     │
              │  │ 1. HarnessTool registry ✓  │     │
              │  │ 2. LangChain tools fallback│     │
              │  └────────────────────────────┘     │
              └──┬──────────────┬──────────────────┘
                 │              │
    ┌────────────▼──┐    ┌─────▼──────────────┐
    │ Harness System│    │  RAG System         │
    │ ┌──────────┐  │    │ ┌────────────────┐  │
    │ │Registry  │  │    │ │RetrievalPipe   │  │
    │ │(8 tools) │  │    │ │EmbeddingSvc    │  │
    │ ├──────────┤  │    │ │RerankerSvc     │  │
    │ │Sandbox   │  │    │ │HybridSearch    │  │
    │ │(no pool) │  │    │ │VectorStore     │  │
    │ ├──────────┤  │    │ └────────────────┘  │
    │ │Security  │  │    │                      │
    │ │(divergent)│  │    │ ⚠ NO HarnessTool    │
    │ ├──────────┤  │    │ ⚠ NO Sandbox        │
    │ │StreamExec│  │    │ ⚠ NO AbortSignal    │
    │ │(dead code)│ │    │ ⚠ NO Permission     │
    │ ├──────────┤  │    └─────────────────────┘
    │ │Pipeline  │  │
    │ │(stub)    │  │
    │ └──────────┘  │
    └───────────────┘
```

## 4. 目标架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                    Unified Harness Layer                          │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Unified Tool Registry (single source)           │ │
│  │  ┌──────────┬──────────┬──────────┬──────────┬───────────┐  │ │
│  │  │File/Shell│  Skill   │   RAG    │  Agent   │  Custom   │  │ │
│  │  │  Tools   │  Tools   │  Tools   │  Tools   │  Tools    │  │ │
│  │  └──────────┴──────────┴──────────┴──────────┴───────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │  Sandbox Pool    │ │SecurityLayer │ │ StreamingExecutor    │ │
│  │  (pre-created)   │ │(unified AST+ │ │ (actually used)      │ │
│  │  auto-scaling    │ │ policy engine│ │                      │ │
│  └──────────────────┘ └──────────────┘ └──────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │           RAG-as-HarnessTool (first-class citizen)           ││
│  │  KB Search│ Doc Query │ Citation Tool │ Embedding Tool       ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. 关键问题 (CRITICAL)

### 发现 1: 三重工具注册表（无同步）

**根因:** 三个独立注册表各自维护，数据从未交叉同步。

| 注册表 | 位置 | 内容 | 使用者 |
|--------|------|------|--------|
| Harness | `harness/tool_registry.py:17` | 8个 HarnessTool 实例 | graph.py 调度/执行 |
| Meta | `agents/tools/meta.py:11` | 17个工具元数据 | `tool_search()` 发现 |
| Agent._tools | `agents/base.py:58` | LangChain 工具列表 | LLM bind_tools |

**影响:**
- Skill 工具通过 `register_tool()` 注册后，**永远不会**出现在 `tool_search()` 结果中
- Resume 等 LangChain 工具不具备 HarnessTool 并发元数据，被归类为独占执行
- 三个注册表可能持有不同版本的同名工具

**修复方案:** 创建 `UnifiedToolRegistry` 类，同时管理三种视图。废弃 `meta.py:_tool_registry`。所有工具注册通过统一入口。

**涉及文件:**
- `src/harness/tool_registry.py` — 新增 UnifiedToolRegistry 类
- `src/agents/tools/meta.py` — `_tool_registry` 改为代理到统一注册表
- `src/agents/tools/__init__.py` — 使用统一注册表
- `src/agents/base.py` — 从统一注册表获取工具
- `src/agents/harness_agent.py` — 使用统一注册表

---

### 发现 2: RAG 与 Harness 完全脱节

**根因:** RAG 子系统构建为独立服务，绕过 Harness 的每个基础设施组件。

具体表现:
- `create_kb_search_tool()` 返回普通 LangChain `@tool`，非 HarnessTool
- 工具执行走 LangChain 降级路径 → 无权限检查、无 AbortSignal
- `RetrievalPipeline` 在沙箱外运行，嵌入/重排序在主进程中执行推理
- 不存在用于 KB 搜索的 HarnessTool

**影响:**
- 用户可通过 RAG 工具绕过安全策略
- 长时间 RAG 查询无法通过 AbortSignal 取消
- 无并发限制 — RAG 可同时启动多次嵌入推理，使 GPU 过载

**修复方案:**
1. 创建 `KBSearchHarnessTool(HarnessTool)` 包装 KB 搜索
2. 通过统一注册表注册
3. 添加 AbortSignal 传播到 RetrievalPipeline
4. 让 `create_kb_search_tool()` 返回委托给 HarnessTool 的 LangChain 包装器

**涉及文件:**
- `src/agents/tools/info.py` — 重构为 HarnessTool
- `src/harness/tool_registry.py` — 注册 KBSearchHarnessTool
- `src/services/rag/retrieval_pipeline.py` — 添加 AbortSignal 参数
- `src/api/v1/conversations.py` — 通过统一注册表获取工具

---

## 6. 高优先级问题 (HIGH)

### 发现 3: SandboxManager 从未作为池使用

**根因:** `SandboxManager` 有完整池管理功能（预创建、健康检查、自动恢复），但每个调用现场创建新实例。

发生位置:
- `src/api/v1/skills.py:166` — `manager = SandboxManager()` → 技能测试
- `src/agents/tools/skill_tools.py:204` — TestSkillTool.execute()
- `src/agents/tools/skill_tools.py:347` — InstallSkillTool.execute()

全局单例 `get_sandbox_manager()` 已定义但**从未被调用**。

**修复方案:**
1. 在应用启动时通过 bootstrap.py 初始化全局单例
2. 替换所有 `SandboxManager()` 为 `get_sandbox_manager()`
3. 使用 `async with manager.acquire() as sandbox:` 模式

### 发现 4: StreamingToolExecutor 是死代码

**根因:** 355 行的 `StreamingToolExecutor` 具有完整调度逻辑（只读并行、写独占、AbortSignal 树、重试、统计），**从未被导入或使用**。`graph.py` 手动实现了自己的调度，缺少信号树、重试和超时管理。

**修复方案:** 让 `_make_tool_node()` 委托给 `StreamingToolExecutor`，移除手动调度代码。

### 发现 5: 对话上下文向量存储是存根

**根因:** `ContextManager` 的 SELECTIVE/HYBRID 策略搜索 `conversation_context` 集合，但**无代码将对话消息写入此集合**。该功能设计正确但不存在——始终返回 0 结果，静默降级为滑动窗口。

**修复方案:**
1. ConversationService 保存消息后嵌入并写入向量集合
2. 添加批处理避免每条消息独立推理
3. 添加 TTL/保留策略

---

## 7. 中等优先级问题 (MEDIUM)

### 发现 6: 安全模型不一致

`ProcessSandbox._check_code_safety()` 有硬编码白名单/黑名单，而 `CodeScanner` 有可配置的 `SecurityPolicy` 级别。两个系统有不同规则——策略禁止的模块可能通过 ProcessSandbox 执行。

**修复方案:** 从 ProcessSandbox 移除 `_check_code_safety()`，统一使用 `CodeScanner` + `SecurityPolicy`。

### 发现 7: 无服务层 DI 容器

服务在端点中按需 `SomeService(db)` 实例化，Embedding/Reranker 使用模块级单例绕过 FastAPI Depends 链。无法跨服务引用，测试困难。

**修复方案:** 创建轻量级 `ServiceContainer`，在启动时注册所有服务，通过 `Depends` 注入。

### 发现 8: Pipeline 包是空存根

`src/harness/pipeline/__init__.py` 是 1 行空文件。若无计划则删除，或添加最小管道接口。

---

## 8. 低优先级问题 (LOW)

| # | 问题 | 影响 |
|---|------|------|
| 9 | Agent 提示词硬编码为 Python 常量 | 添加新 Agent 需改代码 |
| 10 | LangChain 降级路径无 AbortSignal/权限 | 安全一致性缺失 |
| 11 | Planner 提示词跨所有 Agent 共享 | 无法按 Agent 类型定制 |
| 12 | 无工具流式输出 | 用户需等待完整结果 |
| 13 | `_check_code_safety()` 与 `CodeScanner` 重复逻辑 | 与发现 6 合并修复 |

---

## 9. 实施路线图

### 第一阶段: 基础集成 (第 1-2 周)

```
依赖图:
发现3(Sandbox池化) → 发现4(StreamingExecutor) → 发现2(RAG集成)
                                                      ↑
发现1(统一注册表) ────────────────────────────────────┘
```

| 步骤 | 内容 | 涉及核心文件 |
|------|------|-------------|
| 1 | 统一工具注册表 (发现1) | `tool_registry.py`, `meta.py`, `base.py` |
| 2 | 激活 Sandbox 池 (发现3) | `bootstrap.py`, `skills.py`, `skill_tools.py` |
| 3 | 集成 StreamingToolExecutor (发现4) | `graph.py`, `streaming_executor.py` |

### 第二阶段: RAG-Harness 集成 (第 3-4 周)

| 步骤 | 内容 | 涉及核心文件 |
|------|------|-------------|
| 4 | 创建 KBSearchHarnessTool (发现2) | `info.py`, `tool_registry.py`, `retrieval_pipeline.py` |
| 5 | 统一安全模型 (发现6+13) | `process_sandbox.py`, `scanner.py`, `policies.py` |
| 6 | 填充对话上下文 (发现5) | `conversation_service.py`, `context_manager.py` |

### 第三阶段: 服务层清理 (第 5 周)

| 步骤 | 内容 | 涉及核心文件 |
|------|------|-------------|
| 7 | 轻量级 DI 容器 (发现7) | `container.py`, `embedding_service.py`, `reranker_service.py` |
| 8 | 清理存根 + 低优先级项 (发现8-12) | `pipeline/__init__.py`, `prompts/` |

---

## 10. 架构决策记录 (ADR)

### ADR-001: 统一工具注册表作为所有工具层的单一真实来源

**决策:** `UnifiedToolRegistry` 作为所有工具注册的中心点。同时填充 Harness 注册表、`tool_search` 发现和 LangChain 工具注入。不允许绕过。

**后果:** 所有工具注册代码路径必须审计以使用统一注册表。

### ADR-002: RAG 组件必须是头等 HarnessTool 公民

**决策:** 所有 RAG 操作公开为 `HarnessTool` 实例。`RetrievalPipeline` 接收 `AbortSignal` 参数。嵌入和重排序推理在隔离线程/进程中运行。

**后果:** 需重构 `RetrievalPipeline` 以接受信号参数；需为模型推理添加工作线程池。

### ADR-003: 沙箱管理作为全局单例运行，应用启动时预热

**决策:** 全局单例在 lifespan 启动期间初始化，预创建沙箱并管理健康检查。代码执行通过 `get_sandbox_manager()` → `acquire()`。

**后果:** 沙箱初始化失败必须在启动时优雅处理（降级到无沙箱模式）。

### ADR-004: StreamingToolExecutor 是工具调用的唯一调度器

**决策:** 删除 `graph.py` 中手动调度。`_make_tool_node()` 创建 `StreamingToolExecutor` 实例，提交所有调用，通过 `results()` 生成消息。

**后果:** 需重构 `graph.py` 工具节点以接受 executor 参数。

### ADR-005: 服务通过显式 DI 容器解析，而非模块级单例

**决策:** 在启动时创建 `ServiceContainer`。端点通过 `Depends(get_service("name"))` 解析服务。嵌入/重排序器在容器中注册为单例。

**后果:** 所有端点需从直接实例化服务迁移到注入。
