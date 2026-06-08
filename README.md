# Enterprise AI Agent Platform

> 企业级 AI Agent 平台 — 基于 FastAPI + LangGraph + React 18 的全栈 AI 助理系统

[![CI](https://github.com/your-org/agent-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/agent-platform/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![TypeScript](https://img.shields.io/badge/typescript-5.5+-blue)
![React](https://img.shields.io/badge/react-18-61dafb)
![FastAPI](https://img.shields.io/badge/fastapi-0.115+-009688)

---

## 🚀 快速启动

### 环境要求

- **Python** 3.11+
- **Node.js** 20+
- **PostgreSQL** 16+（或使用 Docker）
- **Redis** 7+（或使用 Docker）
- **uv**（Python 包管理器）

### 本地开发

```bash
# 1. 克隆项目
git clone https://github.com/your-org/agent-platform.git
cd agent-platform

# 2. 启动基础设施（PostgreSQL + Redis）
docker run -d --name postgres -p 5432:5432 \
  -e POSTGRES_USER=agent_user -e POSTGRES_PASSWORD=yourpass \
  -e POSTGRES_DB=agent_platform postgres:16-alpine

docker run -d --name redis -p 6379:6379 redis:7-alpine

# 3. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入你的 LLM API Key

# 4. 启动后端
cd backend
uv sync
uv run uvicorn src.main:app --reload --port 8000

# 5. 启动前端（新终端）
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000 查看前端，http://localhost:8000/docs 查看 API 文档。

### Docker Compose 一键部署

```bash
# 开发环境
docker-compose -f docker-compose.yml up -d

# 生产环境
docker-compose -f docker-compose.prod.yml up -d
```

---

## 📁 项目结构

```
agent-project/
├── backend/                    # Python 后端（FastAPI + LangGraph）
│   ├── src/
│   │   ├── agents/             # LangGraph Agent 系统
│   │   ├── api/                # API 路由
│   │   ├── core/               # 核心配置、异常、安全
│   │   ├── db/                 # ORM 模型 + Repository
│   │   ├── llm/                # LLM 提供者工厂
│   │   ├── middleware/         # CORS、日志、限流、租户
│   │   ├── models/             # 数据模型（domain + schemas）
│   │   ├── monitoring/         # Langfuse + OpenTelemetry
│   │   ├── services/           # 业务逻辑 + RAG 系统
│   │   ├── utils/              # 工具函数
│   │   └── vectorstore/        # Chroma / Qdrant 向量存储
│   ├── tests/                  # 测试（单元 + 集成 + RAG 评估）
│   └── pyproject.toml
├── frontend/                   # React 前端（TypeScript + Tailwind）
│   └── src/
│       ├── api/                # Axios API 客户端
│       ├── components/         # UI 组件（shadcn 模式）
│       ├── hooks/              # 自定义 Hooks
│       ├── pages/              # 页面组件
│       ├── routes/             # React Router 配置
│       ├── stores/             # Zustand 状态管理
│       └── types/              # TypeScript 类型
├── docs/                       # 项目文档
├── sandbox/                    # Docker 安全沙箱
├── .github/workflows/          # CI/CD
├── docker-compose.yml          # 开发基础设施
├── docker-compose.prod.yml     # 生产部署
├── AGENTS.md                   # AI 编程助手指南
└── README.md
```

---

## ✨ 核心功能

### 🤖 AI Agent 引擎
- **Plan + ReAct 双模式**：策略规划 + 工具执行，支持工具注册表动态注入
- **知识库 RAG**：HyDE 查询改写 → 混合检索（向量 + BM25）→ Reranker 重排序 → 上下文扩展
- **多 LLM 支持**：DeepSeek / OpenAI / Anthropic，通过配置切换
- **流式输出**：SSE 实时推送 Agent 思考和行动过程

### 📚 知识库管理
- 支持 PDF、Word、Excel、Markdown、图片等多格式文档
- PaddleOCR 中文 OCR + MinerU 深度学习版面分析
- 智能分块（section-aware + 父子块 + 动态分隔符）
- 向量搜索 + 全文搜索 + RRF 融合

### 🔐 安全特性
- 双 Token 认证（JWT + Refresh Token 轮转）
- 多租户数据隔离（行级 + TenantMiddleware）
- API 限流（Redis 滑动窗口）
- Docker 安全沙箱（只读文件系统、网络隔离、无特权）

### 📊 监控与可观测
- Langfuse + OpenTelemetry 全链路追踪
- Prometheus 指标导出 + Grafana 仪表板
- 结构化日志（loguru）
- Token 用量统计与成本追踪

---

## 🔧 配置参考

所有配置项通过环境变量或 `.env` 文件管理。详见 `backend/.env.example`。

核心配置项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | `deepseek` |
| `VECTOR_STORE_TYPE` | 向量数据库 | `chroma` |
| `MONITORING_PROVIDER` | 监控后端 | `langfuse` |
| `MULTI_TENANT_ENABLED` | 多租户隔离 | `false` |
| `KB_HYBRID_SEARCH_ENABLED` | 混合检索 | `true` |
| `KB_OCR_ENABLED` | OCR 提取 | `true` |

---

## 🧪 测试

```bash
# 后端
cd backend
uv run pytest tests/ -v                    # 全部测试
uv run pytest tests/ -v -m "unit"          # 单元测试
uv run pytest tests/ -v -m "eval"          # RAG 评估

# 前端
cd frontend
npm run test                               # Vitest
npm run test:coverage                      # 带覆盖率
```

---

## 📖 文档

| 文档 | 内容 |
|------|------|
| `backend/docs/architecture.md` | 后端完整架构、ER 图、API 路由、认证流程 |
| `docs/frontend-theme-system.md` | 双主题（Emerald/Amber）CSS 规范 |
| `RAG_分析报告.md` | RAG 系统完整分析报告 |
| `AGENTS.md` | AI 编程助手指南 |

---

## 📄 许可证

MIT License
