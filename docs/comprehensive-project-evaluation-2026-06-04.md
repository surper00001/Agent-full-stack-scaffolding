# 全栈项目综合评估报告

> 评估日期：2026-06-04 | 分支：`initial-setup` | 评估范围：前端 + 后端 + 测试 + 安全/DevOps 四维综合

---

## 一、总体评分

```
┌─────────────────────────────────────────────────────┬────────┐
│ 维度                                                │  评分   │
├─────────────────────────────────────────────────────┼────────┤
│ 后端：架构与分层                                    │ 8.0/10 │
│ 后端：代码质量                                      │ 7.5/10 │
│ 后端：错误处理                                      │ 7.0/10 │
│ 后端：性能                                          │ 7.5/10 │
│ 后端：安全性                                        │ 7.0/10 │
│ 后端：依赖管理                                      │ 6.5/10 │
│ 后端：监控可观测性                                  │ 6.5/10 │
│ 前端：组件架构                                      │ 7.0/10 │
│ 前端：状态管理                                      │ 8.0/10 │
│ 前端：TypeScript 使用                               │ 9.0/10 │
│ 前端：性能                                          │ 5.0/10 │
│ 前端：路由导航                                      │ 8.0/10 │
│ 前端：API 层                                        │ 8.0/10 │
│ 前端：UI/UX                                         │ 6.0/10 │
│ 前端：代码质量                                      │ 7.0/10 │
│ 测试：覆盖率                                        │ 5.0/10 │
│ 测试：质量                                          │ 7.0/10 │
│ 测试：组织                                          │ 8.0/10 │
│ 测试：Mock 策略                                     │ 7.0/10 │
│ 测试：E2E/集成                                      │ 5.0/10 │
│ 测试：性能测试                                      │ 3.0/10 │
│ 测试：RAG 评估                                      │ 6.0/10 │
│ 测试：前端测试                                      │ 1.0/10 │
│ 安全：认证授权                                      │ 6.0/10 │
│ 安全：租户隔离                                      │ 2.0/10 │
│ 安全：输入验证                                      │ 7.0/10 │
│ 安全：沙箱安全                                      │ 5.0/10 │
│ 安全：CORS/Headers                                  │ 4.0/10 │
│ 安全：密钥管理                                      │ 5.0/10 │
│ DevOps：CI/CD                                       │ 4.0/10 │
│ DevOps：容器化                                      │ 6.0/10 │
│ DevOps：可观测性                                    │ 6.0/10 │
│ DevOps：文档                                        │ 8.0/10 │
├─────────────────────────────────────────────────────┼────────┤
│ 综合加权评分                                        │ 6.2/10 │
└─────────────────────────────────────────────────────┴────────┘
```

**总体定位**：项目在架构设计、代码规范（尤其前端 TypeScript）、RAG 管线方面已达到中上级水准，但**工程基础设施**（CI/CD、测试覆盖、安全加固）严重不足，当前状态**不具备生产就绪条件**。

---

## 二、核心发现

### 🔴 严重问题 (CRITICAL — 必须立即修复)

#### CRIT-1: 租户隔离形同虚设
- **位置**: `backend/src/middleware/tenant.py` + 所有领域模型
- **问题**: `TenantMiddleware` 从 Header 提取 `tenant_id` 存入 `request.state`，但 **User、Conversation、Skill、Agent 等核心领域模型均无 `tenant_id` 列**。任何 Repository 查询都不按租户过滤。
- **影响**: 若 `MULTI_TENANT_ENABLED=true`，租户 A 可通过 API 直接访问租户 B 的数据。这是企业产品的致命漏洞。
- **修正**: 为所有多租户数据表添加 `tenant_id` 外键，在 `BaseRepository` 中实现自动租户过滤。

#### CRIT-2: `.env.example` 中包含真实 API 密钥
- **问题**: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `BOCHA_API_KEY` 疑似为真实密钥（非占位符）。
- **影响**: Git 历史永久泄露，即使后续删除也无法撤回。
- **修正**: 立即轮换所有泄露的 API 密钥，将 `.env.example` 恢复为纯占位符。

#### CRIT-3: ProcessSandbox 环境变量全量泄露给沙箱
- **位置**: `backend/src/harness/sandbox/process_sandbox.py:170`
- **代码**: `env={**os.environ, "PYTHONPATH": mounted_dir}`
- **影响**: 沙箱中运行的任意代码可以读取 `DEEPSEEK_API_KEY`、`JWT_SECRET_KEY`、`DATABASE_URL` 等所有敏感环境变量。
- **修正**: 创建最小化环境变量白名单，仅传递沙箱必需的路径变量。

#### CRIT-4: 前端 XSS 漏洞（4 处 `dangerouslySetInnerHTML`）
- **位置**:
  - `frontend/src/pages/chat/[id]/index.tsx:88` — 聊天消息 Markdown 渲染
  - `frontend/src/components/kb/kb-block-renderer.tsx:115` — KB 块渲染
  - `frontend/src/components/kb/inline-image-message.tsx:72` — 行内图像消息
  - `frontend/src/pages/conversations/[id].tsx:61` — 对话详情
- **影响**: Agent 输出或知识库内容中的恶意 HTML/JavaScript 可被直接执行。
- **修正**: 用 `react-markdown` + `rehype-sanitize` + `remark-gfm` 替换所有的 `dangerouslySetInnerHTML`。

#### CRIT-5: 前端测试为零
- **现状**: 唯一测试文件 `frontend/test/components/button.test.tsx`（4 个用例）
- **影响**: 前端无任何回归保护，任何改动都可能在不知不觉中破坏功能。
- **修正**: 立即起步，至少覆盖 AuthStore、LoginForm、ChatDetail 核心流程。

---

### 🟠 重要问题 (HIGH — 生产就绪前必须解决)

#### HIGH-1: 无 CI/CD 流水线
- 无 `.github/workflows/`、无 GitLab CI、无 Jenkins 配置。
- Pre-commit 已配置（`ruff` + `mypy` + 格式检查），但无人强制执行。
- **建议**: 创建最小 CI：lint → type-check → test → build。

#### HIGH-2: 无 API 限流
- 登录/注册端点可被暴力攻击。
- `RedisService` 已有 `check_rate_limit` 方法但未集成到中间件。
- **建议**: 使用 `slowapi` 或自实现 Redis 滑动窗口限流中间件。

#### HIGH-3: 前端无懒加载和 Memo
- 所有 20+ 页面在 `routes/index.tsx` 中同步 `import`，首屏加载整个 bundle。
- 无 `React.memo` 使用，每次渲染触发全树重渲染。
- 聊天页面（916 行）在流式过程中频繁重渲染所有子组件。
- **建议**: `React.lazy` + `Suspense` 路由级代码分割；MessageBubble/ToolCallCard 等加 `React.memo`。

#### HIGH-4: 聊天页面巨石组件（916 行）
- `pages/chat/[id]/index.tsx` 包含 8 个内联子组件、全部流式逻辑、上传逻辑、滚动管理。
- 8 个 `useEffect` 钩子，依赖关系复杂。
- **建议**: 拆分为独立模块 — `components/chat/MessageBubble.tsx`, `components/chat/ToolCallCard.tsx`, `hooks/useStreamMessages.ts` 等。

#### HIGH-5: 生命周期函数臃肿
- `backend/src/main.py` 的 `lifespan()` 约 250 行，包含种子数据、内联迁移、模型预热。
- `_add_column_if_missing` 绕过了 Alembic 迁移系统。
- **建议**: 提取到 `src/core/bootstrap.py`，种子数据 + 迁移分离为独立模块。

#### HIGH-6: 全局静默异常吞噬（6+ 处）
- `src/services/knowledge_base_service.py:104-122` — FTS 删除/丢弃
- `src/services/knowledge_base_service.py:617-625` — 取消清理
- `src/monitoring/tracer.py:161-162` — Langfuse flush
- `src/services/skill_service.py:195-196` — 使用统计
- `src/agents/graph.py:436-437` — 工具执行
- `src/main.py:183-184` — 索引创建
- **建议**: 至少 `logger.warning()` 替代 `pass`，对关键路径添加异常上报。

#### HIGH-7: 无 Prometheus 指标导出
- `MetricsCollector` 是纯内存实现，外部无法 Pull。
- 无 `/metrics` 端点。
- **建议**: 集成 `prometheus-client` 或 `starlette-prometheus` 中间件。

#### HIGH-8: 无安全头 (Security Headers)
- 缺少 CSP、HSTS、X-Frame-Options、X-Content-Type-Options。
- CORS 生产配置使用占位符 URL。
- **建议**: 添加 FastAPI 安全头中间件。

---

### 🟡 中等问题 (MEDIUM — 影响工程质量)

#### MED-1: 依赖管理混乱
- `pyproject.toml` 中 `[project.optional-dependencies] dev` 和 `[dependency-groups] dev` 重复。
- 无 `uv.lock` 锁文件，构建不可重现。
- **建议**: 仅保留 `[dependency-groups]`，提交 `uv.lock`。

#### MED-2: `# noqa: E712` 遍地（13 处）
- SQLAlchemy 布尔比较 `== False` 触发 E712。
- **建议**: 使用 `.is_(False)` 或全局忽略 E712。

#### MED-3: 前端无乐观更新
- 删除对话等操作先调 API，等响应成功后才更新本地状态，阻塞 UI。
- **建议**: Zustand 中实现乐观更新 + 失败回滚。

#### MED-4: 无请求去重
- 同一数据被多个组件同时请求时，发出重复 HTTP 调用。
- **建议**: API 层实现 Map-based in-flight 请求去重。

#### MED-5: 前端使用原生 `confirm()`/`alert()`（17+ 处）
- 无法样式化，移动端体验差。
- **建议**: 统一替换为 shadcn AlertDialog。

#### MED-6: 无分布式追踪上下文传播
- OpenTelemetry SDK 已导入但未集成中间件，跨请求的 Trace ID 丢失。
- **建议**: 添加 `OpenTelemetryMiddleware`，日志中自动注入 trace_id/span_id。

#### MED-7: RAG 评估数据集过小且无回归阈值
- Golden dataset 仅 20 条，缺少 `faithfulness`/`answer_relevancy` 指标。
- `assert recall >= 0.0` 是空断言。
- **建议**: 扩展到 50-100 条，设 PASS/FAIL 阈值（如 recall < 0.7 FAIL），实现基线回归对比。

#### MED-8: 嵌入批量大小硬编码
- `knowledge_base_service.py:471` 硬编码 `batch_size = 16`，忽略配置项 `kb_embedding_batch_max`。
- **建议**: 读取配置值。

#### MED-9: 沙箱 AST 检查可绕过
- `process_sandbox.py` 的 `SafetyVisitor` 仅做静态 AST 扫描，`__class__.__bases__[0].__subclasses__()` 等运行时反射可轻易绕过。
- **建议**: 对生产环境使用 Docker/gVisor 级别的运行时隔离。

---

### 🟢 改进建议 (LOW — 提升工程成熟度)

#### LOW-1: 重依赖设为可选
- `paddlepaddle`, `paddleocr`, `torch` (约 2.5GB) 应设为 extras `[kb]` 而非核心依赖。

#### LOW-2: 前端国际化
- 当前全部中文硬编码，无 i18n 框架。
- **建议**: 引入 `react-i18next`。

#### LOW-3: Storybook 组件开发
- 当前 shadcn/ui 组件仅 6 个（Button/Input/Card/Dialog/Toast/Toaster）。
- **建议**: 补充 Select/Table/Tabs/Tooltip/Popover/AlertDialog 等 + Storybook。

#### LOW-4: 无 OpenAPI 生成前端类型
- 前后端各自维护类型定义，容易不同步。
- **建议**: `openapi-typescript` 从 FastAPI OpenAPI schema 自动生成前端类型。

#### LOW-5: 无 CHANGELOG / ADR
- **建议**: 引入 Changesets，`docs/adr/` 记录重要技术决策。

#### LOW-6: 前端 Web Vitals 监控
- **建议**: 上报 LCP/FID/CLS 到 Langfuse 或 Sentry。

#### LOW-7: E2E 测试
- **建议**: Playwright 覆盖核心用户旅程（登录 → 创建 KB → 上传 → 搜索；创建 Agent → 对话）。

#### LOW-8: API 限流的客户端错误信息不友好
- `api/client.ts` 中错误提取链未处理 422 字段级错误和结构化错误码。

#### LOW-9: Token 刷新队列的模块级可变状态
- `api/client.ts:18-22` 的 `isRefreshing`/`failedQueue` 使单元测试困难。

#### LOW-10: 前端无 Vitest 配置文件
- 依赖 Vite 默认配置，路径别名/环境变量可能出错。

---

## 三、与上次评估对比（2026-06-01 → 2026-06-04）

| 维度 | 上次状态 | 本次变化 |
|------|---------|---------|
| Harness 工程 | 设计阶段（8 个新文件计划） | 已实现：12 个 harness 文件 + 5 个测试文件 + 前端 harness 组件 + Skill 管理界面 |
| Docker Compose | 无 | ✅ 已添加 `docker-compose.yml`（沙箱基础设施） |
| Skill CRUD API | 无 | ✅ 已实现 `api/v1/skills.py` + `services/skill_service.py` + 前端 skill 页面 |
| 租户隔离 | 上次评为"完整" | 🔴 深度评估发现实为**外观模式**，数据层无 tenant_id |
| 前端测试 | 上次标注 0 | 仍为 0（仅 1 个按钮测试） |
| 安全评估深度 | 未深入 | 新发现：沙箱环境变量泄露、AST 可绕过、密钥泄露 |

---

## 四、优先级行动计划

### Phase 1：安全与基础（本周 — 2 周）

```
优先级   项目                                    工作量
────────────────────────────────────────────────────
🔴 P0   轮换泄露的 API 密钥 + 清理 .env.example    1h
🔴 P0   为所有领域模型添加 tenant_id 列            4h
🔴 P0   BaseRepository 自动租户过滤                 2h
🔴 P0   ProcessSandbox 环境变量白名单化             2h
🔴 P0   前端 dangerouslySetInnerHTML → react-markdown  4h
🔴 P0   CI/CD 流水线（lint → test → build）        4h
🔴 P0   API 限流中间件集成                          2h
🔴 P0   安全头中间件（CSP/HSTS/XFO）                2h
🔴 P0   前端测试起步（AuthStore + LoginForm）        4h
────────────────────────────────────────────────────
```

### Phase 2：质量与覆盖（2 — 4 周）

```
优先级   项目                                    工作量
────────────────────────────────────────────────────
🟠 P1   聊天页面拆分 + React.lazy + React.memo      8h
🟠 P1   lifespan 提取到 bootstrap.py                3h
🟠 P1   消除所有静默异常吞噬                         2h
🟠 P1   Prometheus /metrics 端点                    3h
🟠 P1   后端 API 路由集成测试                       8h
🟠 P1   前端乐观更新 + 请求去重                      4h
🟠 P1   LLM 调用熔断器 + 重试                       3h
🟠 P1   深度健康检查（DB/Redis/VectorStore）        2h
🟠 P1   原生 confirm/alert → AlertDialog            3h
🟠 P1   嵌入批量大小连接配置                         0.5h
────────────────────────────────────────────────────
```

### Phase 3：工程卓越（1 — 3 个月）

```
优先级   项目                                    工作量
────────────────────────────────────────────────────
🟢 P2   重依赖设为可选 extras                       2h
🟢 P2   国际化 i18n 框架                            8h
🟢 P2   Storybook 组件库                           16h
🟢 P2   Playwright E2E 测试                         16h
🟢 P2   k6 负载测试 + SLA 定义                      8h
🟢 P2   消息队列替换 BackgroundTasks                 16h
🟢 P2   OpenAPI → 前端类型自动生成                  4h
🟢 P2   RAG 评估数据集扩充 + 回归基准                8h
🟢 P2   Feature Flag 系统                           8h
🟢 P2   前端 PWA + 离线缓存                          8h
🟢 P2   uv.lock + 依赖清理                          2h
────────────────────────────────────────────────────
```

---

## 五、亮点总结

尽管存在上述差距，以下方面值得肯定：

1. **RAG 管线工业级完整度** — HyDE + BM25 FTS5 混合检索 + 两阶段 Reranker + MMR 去重 + 上下文扩展，在开源项目中属上乘
2. **前端 TypeScript 零 `any`** — 严格模式 + type-only import + 鉴别联合类型，极其罕见的高纪律性
3. **Axios Token 刷新队列** — `isRefreshing` 锁 + `failedQueue` 并发队列 防 401 风暴，生产级模式
4. **Plan + ReAct 双模型 Agent** — 独立规划模型与执行模型，架构前瞻
5. **上下文管理 4 策略** — Sliding/Summarize/Selective/Hybrid，Token 预算精确控制
6. **文档解析深度** — MinerU 版面分析 + 类型感知分块 + 父子块，覆盖企业 PDF 场景
7. **Harness 工程** — AI 自安装 Skill + 沙箱隔离 + 12 状态生命周期，概念先进
8. **MD 驱动开发** — `CLAUDE.md` + `docs/*.md` 保持架构文档与代码同步

---

**评估结论**：项目核心业务逻辑（Agent、RAG、多租户、上下文管理）已达到中高级工程水准，但**安全防护、测试覆盖、CI/CD 基础设施严重不足**。当前状态**不可直接上生产**。建议按 Phase 1 → Phase 2 → Phase 3 递进补齐，预计 **2 个月可达基本生产就绪**，**4-6 个月可达企业级成熟度**。

---

*本次评估基于 2026-06-04 代码快照，分支 `initial-setup`，综合 4 个专项 Agent 并行分析 + 全栈文件扫描。*
