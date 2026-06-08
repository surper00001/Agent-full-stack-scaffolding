# AGENTS.md

本文件为 Codex（codex.ai）等 AI 编程助手在此仓库中工作时提供指导。

## 项目概述

企业级 AI Agent 平台 — FastAPI 后端 + React 前端。Monorepo 结构，两个独立工作区：`backend/`（Python，uv 管理）和 `frontend/`（TypeScript，npm 管理）。

## 后端命令

所有命令在 `backend/` 目录中执行：

```bash
# 启动开发服务器（自动创建表）
uv run uvicorn src.main:app --reload --port 8000

# Lint & 类型检查
uv run ruff check src/
uv run mypy src/

# 测试
uv run pytest tests/ -v
uv run pytest tests/ -v -m "unit"
uv run pytest tests/ -v -m "not integration"
uv run pytest tests/ -v -k "test_name_pattern"

# 数据库迁移
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head

# 安装依赖
uv sync
uv sync --group dev
```

## 前端命令

所有命令在 `frontend/` 目录中执行：

```bash
npm run dev              # 启动 Vite 开发服务器（端口 3000）
npm run build            # 类型检查 + 生产构建
npm run lint             # ESLint（max-warnings 0）
npm run format           # Prettier 写入
npm run test             # Vitest
npm run test:coverage    # Vitest 带覆盖率
npm run type-check       # tsc --noEmit
```

## 后端架构

分层架构，职责清晰：

```
middleware (CORS → Logging → Tenant) → router → API route → Service → Repository → DB
```

### 关键层级

- **`src/main.py`** — FastAPI 应用工厂，lifespan 管理启动/关闭
- **`src/api/router.py`** — `/api/v1/` 路由聚合
- **`src/api/deps.py`** — 共享 FastAPI 依赖注入
- **`src/core/config.py`** — 所有配置通过 `pydantic-settings` 从 `.env` 加载
- **`src/core/exceptions.py`** — `AppException` 基类及子类，由 main.py 统一捕获
- **`src/db/`** — ORM Base + Mixins（UUID、时间戳、多租户、软删除）+ Generic Repository
- **`src/middleware/`** — CORS、日志、限流、安全头、租户隔离
- **`src/models/domain/`** — SQLAlchemy ORM 模型（仅持久化，无业务逻辑）
- **`src/models/schemas/`** — Pydantic 请求/响应模式
- **`src/services/`** — 业务逻辑层
- **`src/agents/`** — LangGraph Agent 系统（Plan + ReAct）
- **`src/llm/`** — LLM 提供者工厂（DeepSeek / OpenAI / Anthropic）
- **`src/vectorstore/`** — 抽象向量存储接口 + Chroma/Qdrant 实现

### 认证（双 Token 模式）

Access Token 为短生命周期 JWT（HS256，30分钟）。Refresh Token 为随机字符串（bcrypt 哈希存储于 DB，7天）。刷新时旧 token 立即吊销（轮转）。

## 前端架构

React 18 + TypeScript + Vite + Tailwind CSS（shadcn/ui 模式）。

```
src/
├── api/          # Axios API 层，每个资源域一个文件
├── components/   # 组件
│   ├── ui/       # shadcn/ui 原语
│   ├── layout/   # 布局组件
│   └── common/   # 共享组件
├── hooks/        # 自定义 Hooks
├── lib/          # 工具函数
├── pages/        # 页面组件
├── routes/       # React Router 配置
├── stores/       # Zustand stores（扁平，无嵌套）
└── types/        # TypeScript 类型定义
```

## 编码规范

### 通用
- 中文注释和文档，代码标识符使用英文
- 所有公开 API 变化同步更新 `docs/` 中的文档
- 后端使用 Python 3.11+，前端使用 TypeScript 5.5+

### 后端
- 文件编码统一为 UTF-8
- 遵循 ruff 和 mypy strict 规则
- 使用 `src.core.exceptions` 中的自定义异常，避免直接使用 `HTTPException`
- 新服务类接收 `AsyncSession`，内部创建 Repository
- 路由不包含业务逻辑

### 前端
- 使用 `@/` 路径别名映射到 `src/`
- 使用 Zustand 管理状态，避免 Context prop drilling
- 新组件使用 shadcn/ui 模式：`cn()` 工具函数、CVA 变体、Radix 原语
- 遵循 ESLint + Prettier 规则（max-warnings 0）
