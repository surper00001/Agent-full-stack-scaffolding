# Agent Platform - 项目架构文档

> 企业级 AI Agent 后端平台，FastAPI + LangChain + LangGraph + PostgreSQL  
> 最后更新: 2026-05-20

---

## 1. 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| Web 框架 | FastAPI + uvicorn | 异步 HTTP，Scalar API 文档 |
| AI 框架 | LangChain + LangGraph | Agent 编排、工具调用、状态图 |
| ORM | SQLAlchemy 2.0 (async) | 异步会话、Repository 模式 |
| 数据库 | PostgreSQL | 主库，开发环境自动建表 |
| 向量库 | ChromaDB | 默认向量存储，可切换 pgvector |
| 缓存 | Redis | 验证码、会话缓存、LangGraph checkpoint |
| 认证 | python-jose + passlib | JWT 令牌 + bcrypt 密码哈希 |
| 验证码 | pyotp | TOTP 验证码生成与校验 |
| 监测 | LangFuse + OpenTelemetry | LLM 调用追踪、运行时指标 |
| 包管理 | uv | Python 依赖管理与锁定 |
| 代码质量 | ruff + mypy | 代码检查与类型检查 |

---

## 2. 目录结构

```
agent-project/
├── .env                          # 环境变量（含密钥，勿提交）
├── .env.example                  # 环境变量模板
├── pyproject.toml                # 项目配置 + 依赖
├── uv.lock                       # 锁定依赖版本
├── alembic.ini                   # 数据库迁移配置
├── alembic/                      # 迁移脚本
├── docs/                         # 项目文档（MD 文件）
│   └── architecture.md           # 本文件
├── src/
│   ├── main.py                   # FastAPI 应用入口、生命周期、异常处理
│   ├── api/
│   │   ├── router.py             # 路由聚合（/api/v1/...）
│   │   ├── deps.py               # 依赖注入（租户、分页等）
│   │   └── v1/
│   │       ├── health.py         # 健康检查
│   │       ├── auth.py           # 认证: 注册/登录/验证码
│   │       ├── agents.py         # Agent 管理
│   │       └── conversations.py  # 会话管理
│   ├── agents/
│   │   ├── base.py               # Agent 基类（生命周期）
│   │   ├── graph.py              # LangGraph ReAct 状态图
│   │   └── tools.py              # Agent 工具集
│   ├── core/
│   │   ├── config.py             # 全局配置（pydantic-settings）
│   │   ├── exceptions.py         # 统一异常体系
│   │   ├── security.py           # JWT + 密码哈希
│   │   └── redis.py              # Redis 客户端
│   ├── db/
│   │   ├── base.py               # ORM 基类（UUID、时间戳、租户、软删除）
│   │   ├── session.py            # 异步会话管理
│   │   └── repository.py         # 泛型 Repository
│   ├── llm/
│   │   ├── factory.py            # LLM 工厂（DeepSeek/OpenAI/Anthropic）
│   │   └── callbacks.py          # LLM 回调
│   ├── middleware/
│   │   ├── cors.py               # CORS 配置
│   │   ├── logging.py            # 请求日志
│   │   └── tenant.py             # 多租户中间件
│   ├── models/
│   │   ├── domain/               # ORM 领域模型
│   │   │   ├── user.py           # 用户表
│   │   │   ├── tenant.py         # 租户表
│   │   │   ├── agent.py          # Agent 配置表
│   │   │   └── conversation.py   # 会话 + 消息表
│   │   └── schemas/              # Pydantic 请求/响应
│   │       ├── auth.py           # 认证 Schema
│   │       ├── request.py        # 通用请求
│   │       └── response.py       # 通用响应 + 分页
│   ├── services/
│   │   ├── auth_service.py       # 认证业务逻辑
│   │   ├── agent_service.py      # Agent 业务逻辑
│   │   ├── conversation_service.py
│   │   └── tenant_service.py
│   ├── monitoring/
│   │   ├── tracer.py             # LangFuse + OTel 追踪
│   │   └── metrics.py            # 运行时指标
│   ├── utils/
│   │   ├── logger.py             # loguru 日志配置
│   │   └── helpers.py            # 工具函数
│   └── vectorstore/
│       ├── base.py               # 向量库抽象接口
│       └── chroma_store.py       # ChromaDB 实现
└── tests/                        # 测试文件
```

---

## 3. 数据库模型（ER 概要）

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐
│  Tenant  │    │     User     │    │ AgentConfig  │
├──────────┤    ├──────────────┤    ├──────────────┤
│ id       │    │ id           │    │ id           │
│ name     │    │ username     │    │ name         │
│ slug  UK │    │ phone    UK  │    │ agent_type   │
│ is_active│    │ email    UK  │    │ system_prompt│
│          │    │ hashed_pw    │    │ model_name   │
│          │    │ is_active    │    │ temperature  │
│          │    │ is_verified  │    │ is_active    │
└──────────┘    └──────────────┘    └──────────────┘

┌──────────────┐    ┌──────────────┐
│ Conversation │    │   Message    │
├──────────────┤    ├──────────────┤
│ id           │<───│ conversation │
│ title        │    │ role         │
│ agent_type   │    │ content      │
│ message_cnt  │    │ token_count  │
│ status       │    │ metadata_    │
└──────────────┘    └──────────────┘
```

所有业务表均有: `id` (UUID PK), `tenant_id` (多租户隔离), `created_at`, `updated_at`, `is_deleted` (软删除)。

`refresh_tokens` 表独立于多租户体系，仅含: `id`, `token_hash`, `user_id` (FK→users), `expires_at`, `is_revoked`, `created_at`。

---

## 4. API 路由总览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/auth/send-code` | 发送验证码 |
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 用户登录（返回双 Token） |
| POST | `/api/v1/auth/refresh` | 刷新令牌（轮换制） |
| POST | `/api/v1/auth/logout` | 登出（撤销 Refresh Token） |
| GET | `/api/v1/auth/me` | 当前用户信息（需 Bearer Token） |
| GET | `/api/v1/agents` | Agent 配置列表 |
| POST | `/api/v1/agents` | 创建 Agent 配置 |
| GET | `/api/v1/agents/{id}` | Agent 配置详情 |
| PUT | `/api/v1/agents/{id}` | 更新 Agent 配置 |
| DELETE | `/api/v1/agents/{id}` | 删除 Agent 配置 |
| POST | `/api/v1/agents/{id}/run` | 运行 Agent |
| GET/POST | `/api/v1/conversations` | 会话管理 |

---

## 5. 核心设计模式

### 5.1 Repository 模式
所有数据访问通过 `BaseRepository[ModelType]` 进行，提供标准 CRUD：
- `get_by_id()`, `get_by_id_with_tenant()`, `list_all()`, `count()`
- `create()`, `update()`, `soft_delete()`, `hard_delete()`

### 5.2 服务层模式
业务逻辑封装在 Service 类中，接收 `AsyncSession`，内部创建 Repository：
```python
class AuthService:
    def __init__(self, session: AsyncSession):
        self._repo = BaseRepository[User](User, session)
```

### 5.3 统一响应格式
所有接口返回 `APIResponse[T]` 结构：
```json
{"success": true, "code": 20000, "message": "操作成功", "data": {...}}
```

### 5.4 异常体系
`AppException` → 子类异常 → FastAPI exception_handler → 统一 `ErrorResponse`

### 5.5 多租户
- `MULTI_TENANT_ENABLED=false` 时所有记录使用 `tenant_id="default"`
- 开启后通过 Header `x-tenant-id` 注入，Repository 自动过滤

---

## 6. 认证流程（双 Token 机制）

```
注册: send-code → (Redis 存 TOTP secret, 5min TTL) → register(code 验证)
登录: login(account/password) → bcrypt 验证 → 签发双 Token
     ├── Access Token:  JWT (HS256), 30min 有效期, 用于 API 鉴权
     └── Refresh Token: 随机串 (bcrypt 哈希存 DB), 7 天有效期, 用于刷新
刷新: POST /auth/refresh {refresh_token}
     → 验证 refresh token → 撤销旧的 → 签发新双 Token 对（轮换制，防重放）
登出: POST /auth/logout {refresh_token} → 撤销 refresh token
鉴权: Authorization: Bearer <access_token> → 解码 JWT → 获取 user_id
```

- Access Token: `python-jose` JWT，`HS256` 算法，30分钟过期，payload 含 `type: "access"`
- Refresh Token: `secrets.token_urlsafe(64)` 随机生成，bcrypt 哈希后存入 `refresh_tokens` 表
- 轮换制：每次刷新时旧 Refresh Token 立即撤销，防止重放攻击
- 密码: `passlib bcrypt` 哈希
- 验证码: `pyotp.TOTP`，`interval=300`（5分钟有效），Redis 存储 secret

---

## 7. 环境变量速查

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | development | 环境: development/staging/production |
| `APP_PORT` | 8000 | 服务端口 |
| `DB_HOST/PORT/USER/PASSWORD/NAME` | localhost:5432 | PG 连接 |
| `REDIS_HOST/PORT` | localhost:6379 | Redis 连接 |
| `LLM_PROVIDER` | deepseek | deepseek/openai/anthropic |
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key |
| `MULTI_TENANT_ENABLED` | false | 多租户开关 |
| `JWT_SECRET_KEY` | change-me-... | JWT 签名密钥 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | Access Token 过期时间（分钟） |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | 7 | Refresh Token 过期时间（天） |

---

## 8. 开发命令

```bash
# 启动服务（开发模式，自动建表）
uv run uvicorn src.main:app --reload --port 8000

# 代码检查
uv run ruff check src/
uv run mypy src/

# 测试
uv run pytest tests/ -v

# 数据库迁移
uv run alembic upgrade head
```

---

## 9. 扩展指南

- **新增 Agent**: 在 `src/agents/` 创建新文件，继承 `BaseAgent`
- **新增工具**: 在 `src/agents/tools.py` 添加函数
- **新增 API**: 在 `src/api/v1/` 创建路由文件，在 `router.py` 注册
- **新增 ORM 模型**: 在 `src/models/domain/` 创建，继承 `BaseModel`
- **新增服务**: 在 `src/services/` 创建，注入 `AsyncSession`
- **新增异常**: 在 `src/core/exceptions.py` 添加子类

---

## 10. 设计原则

- 贫血模型：ORM 只管持久化，业务逻辑在 Service 层
- 依赖注入：处处用 Depends，不隐藏副作用
- 显式优于隐式：不滥用魔术方法、不隐藏网络调用
- 安全第一：密码 bcrypt 哈希、JWT 签名验证、软删除保护数据
- 测试友好：Repository 可 mock、Service 接收 session 参数
