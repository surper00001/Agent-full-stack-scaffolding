# Harness Engineering — AI 自进化架构

> **设计理念**：让 AI 能自己写工具、测试、安装——像人一样自我进化。  
> **核心流程**：AI 理解需求 → 生成 Skill 代码 → 沙箱测试 → 安全扫描 → 注册到 DB → 热加载至运行时  
> **实施日期**: 2026-06-04 | 基于 `initial-setup` 分支

---

## 目录

1. [架构全景](#一架构全景)
2. [快速开始](#二快速开始)
3. [核心概念](#三核心概念)
4. [工具系统](#四工具系统)
5. [沙箱隔离](#五沙箱隔离)
6. [安全体系](#六安全体系)
7. [Skill 生命周期](#七skill-生命周期)
8. [API 参考](#八api-参考)
9. [前端管理](#九前端管理)
10. [运维指南](#十运维指南)

---

## 一、架构全景

```
用户需求 ──→ Harness Agent (Meta Agent)
               │
               ├─ 1. 理解需求 → 设计 Skill 规格 (Pydantic)
               ├─ 2. 生成 Skill 代码 + Pydantic schema
               ├─ 3. 安全扫描 (AST白名单 + bandit + 模式匹配)
               ├─ 4. WSL2 Docker 沙箱测试
               ├─ 5. 人工审核 (可选，取决于安全级别)
               ├─ 6. 注册到 DB → 热加载到 Agent 运行时
               └─ 7. Agent 立即可用（无需重启）

运行时：StreamingToolExecutor 统一调度所有工具
┌──────────────────────────────────────────────────────┐
│  StreamingToolExecutor                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ read_file │ │web_search│ │ run_shell │  ...        │
│  │ (readOnly │ │(readOnly │ │(exclusive)│              │
│  │  noSafe)  │ │  +safe)  │ │           │              │
│  │ 排队      │ │ ✓parallel│ │ 排队      │              │
│  └──────────┘ └──────────┘ └──────────┘              │
│                                                       │
│  AbortController Tree:                                │
│  userAbort ──→ taskAbort ──→ toolAbort ──→ shellAbort │
└──────────────────────────────────────────────────────┘

沙箱层：WSL2 Docker 容器隔离（自动回退 Process Sandbox）
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Sandbox 1 │  │ Sandbox 2 │  │ Sandbox 3 │  ...
│ CPU:0.5   │  │ CPU:1.0   │  │ CPU:0.5   │
│ Mem:256M  │  │ Mem:512M  │  │ Mem:128M  │
└──────────┘  └──────────┘  └──────────┘
```

### 关键组件

| 组件 | 文件 | 职责 |
|------|------|------|
| **HarnessTool** | `harness/tool_base.py` | 统一工具接口，Pydantic 输入校验 |
| **AbortSignal** | `harness/abort_signal.py` | 可组合树形取消信号 |
| **StreamingExecutor** | `harness/streaming_executor.py` | 流式并行工具调度器 |
| **ToolRegistry** | `harness/tool_registry.py` | DB-backed 工具注册表 + 热加载 |
| **SkillLifecycle** | `harness/skill_lifecycle.py` | 12 状态生命周期状态机 |
| **SandboxManager** | `harness/sandbox/manager.py` | 沙箱池管理 + 自动降级 |
| **CodeScanner** | `harness/security/scanner.py` | 多层安全扫描（AST+Bandit+模式） |
| **SecurityPolicy** | `harness/security/policies.py` | 4 级安全策略配置 |
| **HarnessAgent** | `agents/harness_agent.py` | Meta Agent — AI 写 AI 工具 |

---

## 二、快速开始

### 2.1 前置条件

| 组件 | 要求 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端运行环境 |
| PostgreSQL | 15+ | 主数据库 |
| WSL2 | Windows 11 | 沙箱 Docker 运行环境 |
| Docker | 24+ | 在 WSL2 内安装 |

### 2.2 构建沙箱镜像

```bash
# 在 WSL2 内
cd /mnt/c/Users/.../agent-project/sandbox
docker build -t harness-sandbox:latest .

# 或在 Windows 宿主机
wsl bash -c "cd /mnt/c/.../sandbox && docker build -t harness-sandbox:latest ."
```

### 2.3 启动服务

```bash
# 后端
cd backend
uv run uvicorn src.main:app --reload --port 8000

# 前端
cd frontend
npm run dev
```

启动时 Harness 工具会自动注册内置工具（文件/Shell/网络），无需额外配置。

### 2.4 配置项

在 `backend/.env` 中添加：

```env
# ── Harness Engineering 配置 ──
HARNESS_ENABLED=true                     # 是否启用 Harness Engineering
HARNESS_SANDBOX_ENABLED=true             # 启用沙箱隔离
HARNESS_SANDBOX_POOL_SIZE=3              # 沙箱池预热数量
HARNESS_SANDBOX_MAX_POOL_SIZE=10         # 最大沙箱数量
HARNESS_SANDBOX_TIMEOUT=60               # 默认执行超时（秒）
HARNESS_SANDBOX_PREFER_DOCKER=true       # 优先使用 Docker 沙箱
HARNESS_AUTO_APPROVE_LOW=true            # Low 安全级别自动通过审核
HARNESS_MAX_CODE_LENGTH=10000            # Skill 代码最大字符数
```

### 2.5 用 AI 创建第一个 Skill

通过 API 让 AI 为你生成一个 Skill：

```bash
curl -X POST http://localhost:8000/api/v1/skills/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "requirement": "获取指定 GitHub 仓库的 Star 数量和最近 5 个 Issue",
    "name": "github_repo_stats"
  }'
```

---

## 三、核心概念

### 3.1 HarnessTool 接口

所有工具（内置系统工具 + AI 生成的 Skill）统一实现 `HarnessTool[Input, Output]` 接口：

```python
from pydantic import BaseModel, Field
from src.harness.tool_base import HarnessTool
from src.harness.abort_signal import AbortSignal

class MyToolInput(BaseModel):
    """工具的输入 schema — Pydantic = Python 的 Zod"""
    query: str = Field(description="搜索关键词")
    limit: int = Field(default=10, ge=1, le=100)

class MyTool(HarnessTool[MyToolInput, dict]):
    name = "my_tool"
    description = "我的自定义工具"
    input_schema = MyToolInput
    category = "custom"

    def is_read_only(self, input: MyToolInput) -> bool:
        return True  # 是否只读（影响调度）

    def is_concurrency_safe(self, input: MyToolInput) -> bool:
        return True  # 是否真正并发安全

    async def execute(self, input: MyToolInput, signal: AbortSignal) -> dict:
        signal.throw_if_aborted()  # 定期检查取消信号
        # ... 你的工具逻辑 ...
        return {"result": f"处理完成: {input.query}"}
```

### 3.2 `is_read_only ≠ is_concurrency_safe`

这是 Harness 调度的核心区分。两者独立判断，驱动并行/串行调度策略。

| 场景 | is_read_only | is_concurrency_safe | 调度策略 |
|------|:--:|:--:|------|
| `web_search` GET 请求 | ✅ | ✅ | **并行** asyncio.gather |
| `read_file` 读文件 | ✅ | ❌ | 排队（同文件指针冲突风险） |
| `write_file` 写文件 | ❌ | ❌ | **独占**（互斥锁） |
| `run_shell` 独立命令 | ❌ | ✅ | 可与只读工具并行 |
| `db_query` SELECT | ✅ | ✅ | **并行**（连接池） |
| `git_commit` 写仓库 | ❌ | ❌ | **独占** |
| `glob` 目录扫描 | ✅ | ✅ | **并行** |

### 3.3 AbortSignal 树形取消

```python
from src.harness.abort_signal import AbortSignal, create_signal_chain

# 创建链：用户中断 → 任务取消 → 工具取消 → Shell 超时
user, task, tool, shell = create_signal_chain("user", "task", "tool", "shell")

# 父取消 → 子全部取消
user.abort("用户点击了停止")
# task.aborted == True   (自动传播)
# tool.aborted == True
# shell.aborted == True

# 子取消 → 不影响父或兄弟
shell.abort("命令超时")
# tool.aborted == False   (不受影响)
# task.aborted == False
```

---

## 四、工具系统

### 4.1 内置系统工具（9个）

所有内置工具在应用启动时自动注册。

| 工具 | 类别 | 只读 | 并发安全 | 说明 |
|------|------|:--:|:--:|------|
| `read_file` | file | ✅ | ❌ | 读取文件（支持偏移+行数翻页） |
| `write_file` | file | ❌ | ❌ | 写入文件（自动创建父目录） |
| `edit_file` | file | ❌ | ❌ | 精确字符串替换编辑 |
| `glob` | file | ✅ | ✅ | 递归文件模式匹配 |
| `grep` | file | ✅ | ✅ | 正则内容搜索（ripgrep 级别） |
| `list_dir` | file | ✅ | ✅ | 列出目录内容 |
| `run_shell` | shell | ❌ | ✅ | 沙箱内执行 Shell 命令 |
| `web_fetch` | network | ✅ | ✅ | HTTP GET 获取网页 |
| `web_request` | network | ❌ | ✅ | 通用 HTTP 请求（GET/POST/PUT/DELETE） |

### 4.2 Skill 管理工具（6个 Meta 工具）

| 工具 | 说明 |
|------|------|
| `search_skills` | 搜索已注册的 Skill |
| `generate_skill_code` | AI 生成 Skill 代码和 Pydantic schema |
| `test_skill` | 在沙箱中测试 Skill |
| `scan_skill` | 安全扫描 Skill 代码 |
| `register_skill` | 验证并注册 Skill 到 DB |
| `install_skill` | 完整安装流水线（扫描→测试→验证→注册） |

### 4.3 工具注册表

```python
from src.harness.tool_registry import register_tool, get_tool, list_tools

# 注册自定义工具
register_tool(MyTool())

# 查找工具
tool = get_tool("my_tool")

# 列出所有已启用的工具
tools = list_tools(enabled_only=True)

# 按类别过滤
file_tools = list_tools(category="file")
```

---

## 五、沙箱隔离

### 5.1 沙箱架构

```
SandboxManager (池管理)
  ├── 探测 Docker 可用性（含功能验证）
  ├── Docker 可用 → WSLDockerSandbox
  │   ├── wsl bash -c "docker run --rm ..."
  │   ├── CPU/内存/磁盘限制
  │   └── 网络模式: none/internal/whitelist/full
  └── Docker 不可用 → ProcessSandbox (自动降级)
      ├── subprocess + AST 白名单
      ├── 独立临时目录
      └── 超时控制
```

### 5.2 使用沙箱

```python
from src.harness.sandbox.manager import get_sandbox_manager

manager = get_sandbox_manager()
await manager.start()

# 方式 1：上下文管理器
async with manager.acquire() as sandbox:
    result = await sandbox.execute_code("print('hello')")
    print(result.stdout)  # "hello"

# 方式 2：快捷方法
result = await manager.execute_code(
    "import json; print(json.dumps({'ok': True}))",
    timeout=30,
)

await manager.shutdown()
```

### 5.3 沙箱配置

```python
from src.harness.sandbox.base import SandboxConfig, NetworkMode

config = SandboxConfig(
    image="harness-sandbox:latest",
    cpu_limit=0.5,         # CPU 核心数
    memory_mb=256,         # 内存限制
    disk_mb=512,           # 磁盘限制
    timeout_seconds=60,    # 默认超时
    network=NetworkMode.NONE,  # 网络隔离
    read_only_rootfs=True,     # 根文件系统只读
)
```

### 5.4 WSL2/Docker 前置条件

```bash
# 检查 WSL 版本
wsl --version

# 检查 WSL2 发行版
wsl -l -v

# 在 WSL2 内安装 Docker
# （如果使用 Docker Desktop，确保启用了 WSL2 backend）

# 在 WSL2 内启动 Docker daemon
sudo service docker start

# 或使用 Docker Desktop（自动管理）
```

---

## 六、安全体系

### 6.1 多层安全架构

```
Skill 代码
  │
  ├─ 第 1 层：Pydantic 输入校验
  │   └─ 类型安全、范围校验、必填字段
  │
  ├─ 第 2 层：AST 白名单/黑名单
  │   ├─ 禁止模块: os, subprocess, socket, ctypes...
  │   ├─ 禁止函数: eval, exec, compile, __import__...
  │   └─ 禁止模式: os.system(), rm -rf, while True...
  │
  ├─ 第 3 层：复杂度限制
  │   ├─ 代码行数 ≤ 500
  │   ├─ AST 节点数 ≤ 2000
  │   └─ 执行超时
  │
  ├─ 第 4 层：Bandit 静态分析（可选）
  │   └─ 专业 Python 安全扫描工具
  │
  └─ 第 5 层：Docker 容器隔离
      ├─ 网络隔离 (network=none)
      ├─ 资源限制 (CPU/内存/磁盘)
      ├─ 只读根文件系统
      └─ 非 root 用户
```

### 6.2 安全级别

| 级别 | 网络 | 文件系统 | 内存 | 超时 | 审核 |
|------|:--:|:--:|------|------|:--:|
| **low** | ❌ | ❌ | 128MB | 30s | ❌ |
| **medium** | 白名单 | 只读 | 256MB | 60s | ❌ |
| **high** | ❌ | ❌ | 64MB | 15s | ✅ |
| **critical** | ❌ | ❌ | 32MB | 10s | ✅ |

### 6.3 安全扫描

```python
from src.harness.security.policies import POLICY_MEDIUM
from src.harness.security.scanner import CodeScanner

scanner = CodeScanner(POLICY_MEDIUM)
result = scanner.scan(code)

print(f"评分: {result.score}/100")
print(f"通过: {result.passed}")
for finding in result.findings:
    print(f"  [{finding.severity}] {finding.message} (第{finding.line}行)")
```

**发现严重性：** CRITICAL (-30分) > ERROR (-15分) > WARNING (-5分) > INFO (0分)

---

## 七、Skill 生命周期

### 7.1 状态机

```
draft ──→ testing ──→ pending_review ──→ approved ──→ published ──→ active
  │          │              │                                                  │
  │          │              └──→ rejected ──→ draft（修改后重新提交）            │
  │          │                                                                  │
  └──────────┴──────────────────────────────────────────────────→ archived     │
                                                                               │
  active ──→ deprecated ──→ archived                                          │
```

### 7.2 状态说明

| 状态 | 可编辑 | 可用 | 说明 |
|------|:--:|:--:|------|
| `draft` | ✅ | ❌ | 初始草稿，AI 生成或手动创建 |
| `testing` | ✅ | ❌ | 沙箱测试中 |
| `pending_review` | ❌ | ❌ | 等待管理员审核 |
| `approved` | ❌ | ✅ | 审核通过 |
| `rejected` | ❌ | ❌ | 审核驳回，需修改 |
| `published` | ❌ | ✅ | 已发布 |
| `active` | ❌ | ✅ | 已激活，Agent 可用 |
| `deprecated` | ❌ | ❌ | 已弃用，不建议使用 |
| `archived` | ❌ | ❌ | 已归档 |

### 7.3 使用方式

```python
from src.harness.skill_lifecycle import SkillLifecycle, SkillStatus

lc = SkillLifecycle()

# 标准审批流程
lc.transition(SkillStatus.TESTING, reason="AI 生成完成")
lc.transition(SkillStatus.PENDING_REVIEW, reason="测试通过")
lc.transition(SkillStatus.APPROVED, reason="管理员审核通过")
lc.transition(SkillStatus.PUBLISHED, reason="发布")
lc.transition(SkillStatus.ACTIVE, reason="激活")

# 获取允许的下一步状态
allowed = lc.get_allowed_transitions()
print(allowed)  # {SkillStatus.DEPRECATED, SkillStatus.TESTING, ...}

# 强制转换（管理员跳过中间状态）
lc.force_transition(SkillStatus.DRAFT, reason="紧急回滚")
```

### 7.4 Skill 代码规范

AI 生成的 Skill 代码必须遵循以下规范：

```python
"""Skill 描述（可选但推荐）"""
import json
from typing import Any

def execute(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Skill 入口函数。

    Args:
        input_data: 输入数据（由 Pydantic schema 校验后传入）

    Returns:
        dict: 必须包含 "success" (bool) 字段
              - 成功: {"success": True, "result": ..., "data": ...}
              - 失败: {"success": False, "error": "错误描述"}
    """
    # 你的逻辑...
    return {"success": True, "result": "Hello, World!"}
```

**允许的导入：** `json`, `math`, `datetime`, `collections`, `itertools`, `functools`, `re`, `string`, `typing`, `dataclasses`, `pathlib`, `hashlib`, `base64`, `uuid`, `csv`（取决于安全级别）

**禁止的导入：** `os`, `subprocess`, `socket`, `ctypes`, `importlib`, `sys`, `shutil`（所有级别）

---

## 八、API 参考

### 8.1 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/skills` | 列出 Skill（分页+搜索+过滤） |
| `POST` | `/api/v1/skills` | 手动创建 Skill |
| `GET` | `/api/v1/skills/{id}` | Skill 详情（含代码） |
| `PUT` | `/api/v1/skills/{id}` | 更新 Skill |
| `DELETE` | `/api/v1/skills/{id}` | 删除 Skill |
| `POST` | `/api/v1/skills/{id}/test` | 沙箱测试执行 |
| `POST` | `/api/v1/skills/{id}/publish` | 发布（扫描+激活） |
| `POST` | `/api/v1/skills/{id}/deprecate` | 弃用标记 |
| `POST` | `/api/v1/skills/{id}/status/{target}` | 状态转换 |
| `POST` | `/api/v1/skills/generate` | AI 生成 Skill |

### 8.2 查询参数

```
GET /api/v1/skills?page=1&page_size=20&search=weather&status=active&sort=usage_count_desc
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 |
| `search` | str | - | 关键词搜索（模糊匹配名称和描述） |
| `status` | str | - | 按状态过滤 |
| `sort` | str | `created_at_desc` | 排序: `created_at_desc/asc`, `usage_count_desc/asc`, `name_asc` |

### 8.3 AI 生成 Skill

```json
POST /api/v1/skills/generate
{
    "requirement": "获取指定城市的天气信息",
    "name": "weather_fetcher",
    "security_level": "medium"
}

Response:
{
    "success": true,
    "code": 20000,
    "message": "成功",
    "data": {
        "code": "import json\nfrom typing import Any\n\ndef execute(input_data)...\n",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
        },
        "name": "weather_fetcher",
        "security_level": "medium",
        "security_score": 95,
        "description": "获取指定城市的天气信息"
    }
}
```

### 8.4 沙箱测试

```json
POST /api/v1/skills/{id}/test
{
    "input": {"city": "北京"},
    "timeout": 30
}

Response:
{
    "success": true,
    "data": {
        "passed": true,
        "output": {"success": true, "result": "北京今天晴，25°C"},
        "duration_ms": 150.3,
        "exit_code": 0,
        "sandbox_type": "docker"
    }
}
```

---

## 九、前端管理

### 9.1 导航

前端管理界面入口：**侧边栏 → Skill管理**（Zap 图标）

### 9.2 Skill 列表页

- **搜索**：按名称/描述模糊搜索
- **状态过滤**：下拉框选择 draft/testing/active/deprecated...
- **排序**：按创建时间、使用次数排列
- **快速操作**：发布、弃用、删除（内联按钮）
- **分页**：服务端分页

### 9.3 Skill 详情页

- **代码编辑器**：在线编辑 Skill 代码（draft/testing 状态）
- **元数据卡片**：
  - 使用次数
  - 成功率 (基于最近 N 次执行)
  - 平均耗时
  - 并发安全性
- **沙箱测试面板**：
  - JSON 输入编辑器
  - 执行按钮
  - 实时结果展示
- **安全信息**：安全级别 + 安全评分
- **生命周期**：当前状态 + 可用状态转换按钮

---

## 十、运维指南

### 10.1 监控指标

| 指标 | 来源 | 说明 |
|------|------|------|
| `harness_sandbox_pool_size` | SandboxManager.stats | 当前池大小 |
| `harness_sandbox_in_use` | SandboxManager.stats | 使用中沙箱数 |
| `harness_sandbox_total_created` | SandboxManager.stats | 累计创建数 |
| `harness_sandbox_total_acquired` | SandboxManager.stats | 累计获取数 |
| `harness_tools_registered` | ToolRegistry | 已注册工具数 |
| `harness_skills_active` | SkillService | 活跃 Skill 数 |
| `skill_execution_duration_ms` | Skill.avg_duration_ms | 平均执行耗时 |

### 10.2 日志

Harness 相关日志使用 loguru，标签为 `harness.*`：

```bash
# 查看 Harness 日志
grep "harness" backend/logs/app.log

# 日志级别
# DEBUG  - 沙箱池健康检查
# INFO   - 工具注册/加载、Skill 状态变更
# WARNING - Docker 不可用降级、沙箱回收
# ERROR  - 工具执行失败、Skill 加载失败
```

### 10.3 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| "Docker 不可用" | WSL2/Docker 未启动 | `wsl bash -c "sudo service docker start"` |
| 沙箱执行超时 | Skill 代码有死循环/网络调用 | 降低超时值，检查安全策略 |
| Skill 加载失败 | 数据库中的代码被篡改（hash 不匹配） | 重新发布 Skill |
| 工具未注册 | 启动时 DB 连接失败 | 检查数据库连接，重启服务 |

### 10.4 安全建议

1. **生产环境务必启用沙箱**：`HARNESS_SANDBOX_ENABLED=true`
2. **审核 high/critical 级别 Skill**：`HARNESS_AUTO_APPROVE_LOW=true`（仅自动通过 low）
3. **定期清理过期容器**：启用 `sandbox-cleaner` 服务（docker compose profile=full）
4. **限制 AI 生成 Skill 的代码长度**：`HARNESS_MAX_CODE_LENGTH=10000`
5. **监控异常执行**：关注 `harness_sandbox_total_failed` 指标

### 10.5 性能调优

| 参数 | 建议值 | 说明 |
|------|--------|------|
| `HARNESS_SANDBOX_POOL_SIZE` | 3-5 | 预热沙箱数，减少冷启动 |
| `HARNESS_SANDBOX_MAX_POOL_SIZE` | 10-20 | 并发上限 |
| `HARNESS_SANDBOX_TIMEOUT` | 30-60 | 默认超时（秒） |
| SandboxConfig.cpu_limit | 0.5-2.0 | 根据 Skill 复杂度 |
| SandboxConfig.memory_mb | 128-512 | 内存限制 |

### 10.6 备份与恢复

```sql
-- 导出所有 Skill（含代码）
SELECT name, version, code, input_schema, output_schema, security_level, status
FROM skills
WHERE is_deleted = false;

-- 备份整个 skills 表
pg_dump -t skills agent_platform > skills_backup.sql;
```

---

## 附录：目录结构

```
agent-project/
├── docker-compose.yml               # Harness Sandbox 基础设施
├── sandbox/
│   └── Dockerfile                   # 沙箱执行镜像
├── backend/
│   └── src/
│       └── harness/                 # Harness Engineering 核心
│           ├── tool_base.py         # HarnessTool 抽象基类
│           ├── abort_signal.py      # AbortSignal 树形取消
│           ├── streaming_executor.py # 流式并行调度器
│           ├── tool_registry.py     # DB-backed 注册表
│           ├── skill_lifecycle.py   # 生命周期状态机
│           ├── sandbox/
│           │   ├── base.py          # 沙箱抽象接口
│           │   ├── wsl_docker_sandbox.py  # WSL2 Docker 沙箱
│           │   ├── process_sandbox.py     # 进程沙箱（降级）
│           │   └── manager.py       # 沙箱池管理器
│           ├── security/
│           │   ├── scanner.py       # 代码安全扫描
│           │   └── policies.py      # 4 级安全策略
│           └── pipeline/            # 扩展预留
│               ├── generator.py
│               ├── tester.py
│               └── publisher.py
```
