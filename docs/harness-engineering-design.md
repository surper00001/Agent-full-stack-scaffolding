# Harness Engineering — 智能体自进化架构设计 v2

> AI 自我安装 Skill + 沙箱隔离 + 流式并行工具调度  
> 设计日期: 2026-06-04 | 基于 `initial-setup` 分支

---

## 一、现状分析

### 1.1 项目全貌

```
agent-project/
├── backend/                          # FastAPI + LangChain/LangGraph 后端
│   ├── src/
│   │   ├── main.py                   # 应用工厂、生命周期
│   │   ├── api/v1/                   # REST API (auth, agents, conversations, kb, admin...)
│   │   ├── agents/                   # Plan+ReAct 双模型 Agent (16个静态工具)
│   │   ├── core/                     # 配置、异常、安全、Redis
│   │   ├── db/                       # ORM 基类、Repository、会话
│   │   ├── llm/                      # LLM 工厂 (DeepSeek/OpenAI/Anthropic)
│   │   ├── middleware/               # CORS、日志、多租户
│   │   ├── models/                   # 领域模型 + Pydantic Schema
│   │   ├── services/                 # 业务 + RAG 管线 (minerU/embedding/reranker/BM25...)
│   │   ├── monitoring/               # LangFuse + OTel
│   │   └── vectorstore/              # ChromaDB/Qdrant
├── frontend/                         # React 18 + TS + Vite + Tailwind (shadcn/ui)
└── docs/
```

### 1.2 现有 Agent 架构

```
START → planner (Plan LLM) → executor (Execute LLM + tools) ⇄ tools → END
         ↓                         ↓
    结构化 JSON 计划            ReAct 循环 (max 15 iter)
```

**痛点：**
- 工具在 `tools/__init__.py` 硬编码为 `_ALL_TOOLS` 列表
- 工具注册表存内存，重启丢失
- 工具同步执行，无并行调度
- 无沙箱隔离，工具直接在 Agent 进程内运行
- AI 没有文件读写、命令执行等系统级能力

---

## 二、Harness Engineering 核心模式

### 2.1 统一 Tool 接口（Pydantic = Python 的 Zod）

```python
from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

Input = TypeVar("Input", bound=BaseModel)
Output = TypeVar("Output")

class HarnessTool(Generic[Input, Output], ABC):
    """统一工具接口 — Pydantic 做输入校验"""

    # ── 静态元数据 ──
    name: str                          # 唯一标识
    description: str                   # LLM 看的使用说明
    input_schema: type[Input]          # Pydantic Model → 自动生成 JSON Schema

    # ── 调度基石 ──
    def is_enabled(self) -> bool: ...             # Feature Flag / 环境判断
    def is_read_only(self, input: Input) -> bool: ...  # 只读 → 可并行
    def is_concurrency_safe(self, input: Input) -> bool: ... # 真正并发安全

    # ── 生命周期 ──
    def validate_input(self, input: Input) -> ValidationResult: ...
    def check_permissions(self, input: Input) -> PermissionResult: ...
    async def execute(self, input: Input, signal: AbortSignal) -> Output: ...

    # ── 渲染 ──
    def render_result(self, output: Output) -> str: ...
```

**关键区分：`is_read_only ≠ is_concurrency_safe`**

| 场景 | is_read_only | is_concurrency_safe |
|------|:--:|:--:|
| `web_search` 纯 GET 请求 | ✅ | ✅ |
| `read_file` 读文件 | ✅ | ❌ (同文件指针冲突) |
| `write_file` 写文件 | ❌ | ❌ |
| `run_shell` 独立命令 | ❌ | ✅ (各自隔离) |
| `db_query` SELECT | ✅ | ✅ (连接池) |
| `git_commit` 写仓库 | ❌ | ❌ (不能并行) |

### 2.2 AbortController 树形取消

```python
from asyncio import Event

class AbortSignal:
    """可组合的取消信号 — 父取消→子全部取消"""
    def __init__(self, parent: "AbortSignal | None" = None):
        self._aborted = Event()
        self._reason: str | None = None
        # 父取消 → 子自动取消（单向继承）
        if parent:
            parent.on_abort(lambda r: self.abort(r))

    @property
    def aborted(self) -> bool: ...
    @property
    def reason(self) -> str | None: ...
    def abort(self, reason: str = "cancelled") -> None: ...
    def on_abort(self, callback: Callable[[str], None]) -> None: ...
    def throw_if_aborted(self) -> None: ...  # 工具内定期调用

# 使用场景：
# main_ctrl = AbortSignal()              # 用户中断 → 全部停止
# task_ctrl = AbortSignal(main_ctrl)     # 任务失败 → 只停这个任务
# shell_ctrl = AbortSignal(task_ctrl)    # Shell 超时 → 只停这个 Shell
```

### 2.3 流式工具执行器 (Streaming Tool Executor)

核心思想：**LLM 边输出边执行工具，不等 LLM 说完。**

```python
class ToolTask:
    id: str
    tool: HarnessTool
    input: BaseModel
    status: Literal["queued", "running", "done", "failed"]
    is_concurrency_safe: bool
    is_read_only: bool
    abort_signal: AbortSignal

class StreamingToolExecutor:
    """LLM 产出 tool_call 立即调度，不等待完整响应"""

    def __init__(self, max_parallel: int = 8):
        self._queue: list[ToolTask] = []
        self._in_flight: set[str] = set()
        self._completed: list[ToolResult] = []

    def submit(self, tool_call: ToolCall) -> None:
        """收到 LLM tool_call chunk 时立即调用"""
        task = ToolTask(...)
        self._queue.append(task)
        self._try_schedule(task)

    def _try_schedule(self, task: ToolTask) -> None:
        """检查并发约束后调度"""
        # 检查：有无独占工具在执行？
        has_exclusive = any(
            not self._get_task(tid).is_concurrency_safe
            for tid in self._in_flight
        )
        if has_exclusive and not task.is_concurrency_safe:
            return  # 排队等待

        # 检查：非只读工具只能独占
        if not task.is_read_only and len(self._in_flight) > 0:
            return

        self._execute_task(task)

    def drain_completed(self) -> Generator[ToolResult, None, None]:
        """保持输出顺序的已完成结果"""
        while self._completed:
            yield self._completed.pop(0)

    @property
    def pending_count(self) -> int: ...
```

**执行模型对比：**

```
传统 ReAct：LLM输出全部tool_calls → 逐个执行 → LLM再次推理 → ...
              [========LLM========][==T1==][==T2==][==LLM==]...

流式执行器：LLM边输出边调度 → 安全约束下并行
              [==LLM==]
                [==T1==]
                  [==T2==]
                    [==T3==]   ← T1/T2/T3 可能并行
              → 结果按输入顺序返回给 LLM
```

---

## 三、总体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      Harness Engineering                          │
│                                                                    │
│  用户需求 ──→ Harness Agent (Meta Agent)                           │
│                 │                                                  │
│                 ├─ 1. 理解需求 → 设计 Skill 规格 (Pydantic)        │
│                 ├─ 2. 生成 Skill 代码 + Pydantic schema            │
│                 ├─ 3. 安全扫描 (AST白名单 + bandit)                │
│                 ├─ 4. WSL Docker 沙箱测试                          │
│                 ├─ 5. 人工审核 (可选)                              │
│                 ├─ 6. 注册到 DB → 热加载到 StreamingExecutor       │
│                 └─ 7. Agent 立即可用                               │
│                                                                    │
│  运行时：StreamingToolExecutor 统一调度所有工具                    │
│  ┌──────────────────────────────────────────────────────┐         │
│  │  StreamingToolExecutor                                │         │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐              │         │
│  │  │ read_file │ │web_search│ │ run_shell │  ...        │         │
│  │  │ (readOnly)│ │(readOnly)│ │(exclusive)│              │         │
│  │  │ ✓parallel │ │✓parallel │ │ 排队      │              │         │
│  │  └──────────┘ └──────────┘ └──────────┘              │         │
│  │                                                       │         │
│  │  AbortController Tree:                                │         │
│  │  userAbort ──→ taskAbort ──→ shellAbort               │         │
│  └──────────────────────────────────────────────────────┘         │
│                                                                    │
│  沙箱层：WSL2 Docker 容器隔离                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                       │
│  │ Sandbox 1 │  │ Sandbox 2 │  │ Sandbox 3 │  ...                 │
│  │ (Docker)  │  │ (Docker)  │  │ (Docker)  │                      │
│  │ CPU:0.5   │  │ CPU:1.0   │  │ CPU:0.5   │                      │
│  │ Mem:256M  │  │ Mem:512M  │  │ Mem:128M  │                      │
│  └──────────┘  └──────────┘  └──────────┘                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 四、新增目录结构

```
backend/src/
├── harness/                              # ★ Harness Engineering 核心
│   ├── __init__.py
│   ├── tool_base.py                      # ★ HarnessTool 抽象基类 (2.1)
│   ├── abort_signal.py                   # ★ AbortSignal 树形取消 (2.2)
│   ├── streaming_executor.py             # ★ StreamingToolExecutor (2.3)
│   ├── tool_registry.py                  # ★ DB-backed Skill 注册表 + 热加载
│   ├── skill_lifecycle.py                # Skill 生命周期状态机
│   ├── sandbox/
│   │   ├── __init__.py
│   │   ├── base.py                       # Sandbox 抽象接口
│   │   ├── wsl_docker_sandbox.py         # ★ WSL2 Docker 沙箱
│   │   ├── process_sandbox.py            # 子进程沙箱（开发用）
│   │   └── manager.py                   # 沙箱池管理器
│   ├── security/
│   │   ├── __init__.py
│   │   ├── scanner.py                    # 代码安全扫描
│   │   └── policies.py                   # 安全策略配置
│   └── pipeline/
│       ├── __init__.py
│       ├── generator.py                  # Skill 代码生成 Agent
│       ├── tester.py                     # Skill 测试验证
│       └── publisher.py                  # Skill 发布流程
├── agents/
│   ├── harness_agent.py                  # ★ Harness Meta Agent
│   └── tools/
│       ├── file_tools.py                 # ★ 文件系统工具 (read/write/edit/glob/grep)
│       ├── shell_tool.py                 # ★ Shell 命令执行
│       ├── skill_tools.py                # ★ Skill 管理工具
│       └── browser_tool.py               # ★ 浏览器工具 (playwright)
├── models/domain/
│   └── skill.py                          # ★ Skill ORM 模型
├── models/schemas/
│   └── skill.py                          # ★ Skill Pydantic Schema
├── api/v1/
│   └── skills.py                         # ★ Skill CRUD API
└── services/
    └── skill_service.py                  # ★ Skill 业务服务
```

---

## 五、分步改造计划（重排后）

### 第 1 步：基础设施 — Tool 基类 + AbortSignal + 数据模型

**核心文件：**
- `harness/tool_base.py` — `HarnessTool[Input, Output]` 抽象基类（Pydantic v2）
- `harness/abort_signal.py` — `AbortSignal` 可组合取消信号
- `models/domain/skill.py` — Skill ORM（含 `concurrency_safe`, `read_only` 字段）
- `models/schemas/skill.py` — Skill Pydantic Schema

**为什么这步最重要：** 后续所有工具和调度都依赖这个接口定义。

### 第 2 步：流式工具执行器

**核心文件：**
- `harness/streaming_executor.py` — `StreamingToolExecutor`

改造 `graph.py` 的 tool_node，从同步逐个调用改为流式并行调度。

### 第 3 步：系统级工具 — 文件 + Shell + 网络

**核心文件：**
- `agents/tools/file_tools.py` — `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- `agents/tools/shell_tool.py` — `run_shell` (沙箱内执行)
- `agents/tools/browser_tool.py` — `web_fetch`, `web_search` 增强

这些是 AI 自进化的基础能力——能读代码、写代码、跑命令。

### 第 4 步：沙箱系统 — WSL2 Docker

**核心文件：**
- `harness/sandbox/wsl_docker_sandbox.py`
- `harness/sandbox/manager.py`

关键适配：
- Windows 宿主机 → WSL2 内 Docker daemon
- 容器内挂载 `/workspace` (临时目录)
- 网络：默认隔离，白名单域名可访问
- 资源限制：CPU shares, Memory limit, disk quota

### 第 5 步：安全扫描

**核心文件：**
- `harness/security/scanner.py`
- `harness/security/policies.py`

### 第 6 步：Skill Registry — DB-backed 热加载

**核心文件：**
- `harness/tool_registry.py`
- `harness/skill_lifecycle.py`

### 第 7 步：Harness Meta Agent

**核心文件：**
- `agents/harness_agent.py`
- `agents/tools/skill_tools.py`

### 第 8 步：API + Service 层

### 第 9 步：前端 Skill 管理界面

### 第 10 步：集成 + 测试 + 文档

---

## 六、执行顺序依赖图

```
第1步 ──→ 第2步 ──→ 第6步 ──→ 第7步 ──→ 第8步 ──→ 第9步 ──→ 第10步
  │                  ↗
  └──→ 第3步 ──→ 第4步 ──→ 第5步 ──┘
```

- 第1步 (工具基类+模型) 和第3步 (系统工具) 可并行
- 第4步 (沙箱) 依赖第3步（需要文件/Shell工具测试沙箱）
- 第5步 (安全) 依赖第4步（需要沙箱环境跑扫描）
- 第6步 (Registry) 依赖第1步 + 第5步结果

---

## 七、技术决策（更新）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 输入校验 | Pydantic v2 BaseModel | Python 版 Zod，直接生成 JSON Schema |
| 工具接口 | 抽象基类 + 泛型 | 统一 is_read_only / is_concurrency_safe |
| 取消机制 | AbortSignal 树 | 细粒度：用户中断/任务失败/超时 分别可控 |
| 调度策略 | StreamingToolExecutor | LLM 边输出边执行，不等待完整响应 |
| 沙箱 | WSL2 Docker | Windows 宿主机，Docker 在 WSL 内 |
| 安全性 | 多层：Pydantic校验 + AST白名单 + bandit + Docker隔离 |
| Skill 存储 | DB + 内存缓存 | 持久化 + 热加载 |
