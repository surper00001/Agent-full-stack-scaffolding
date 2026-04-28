# 2025.03-2025.06 企业级多模态知识库智能问答Agent

## 角色

核心开发（独立开发）

## 技术栈

Python / FastAPI / LangChain / LangGraph / PostgreSQL / ChromaDB / Redis / React + TypeScript / LangFuse / OpenTelemetry / Docker

## 项目背景

针对企业内部分散文档检索效率低、跨部门知识共享困难、非结构化数据（PDF/Word/Excel/图片）利用率不足的痛点，设计并独立开发了一套企业级多模态知识库智能问答Agent平台，实现"文档解析→模态转换→向量存储→智能问答→效果追踪"全流程自动化，支撑企业知识资产的高效复用与精准检索。

## 核心贡献

### 1. 双阶段Agent推理架构设计

设计 Plan + ReAct 双阶段 Agent 执行引擎，基于 LangGraph 构建有状态推理图。Planner 阶段由独立推理模型（低温度）对用户意图进行结构化拆解，输出多步骤执行计划；Executor 阶段基于 ReAct 循环逐步执行工具调用，支持条件路由与最大迭代保护（防止死循环）。支持 Plan Model 与 Execute Model 独立选型，在复杂多步推理与简单对话间灵活切换。

- LangGraph StateGraph 编排，状态持久化至 SQLite（AsyncSqliteSaver），支持对话断点恢复
- 支持 DeepSeek / OpenAI / Anthropic 三厂 LLM 统一接入，通过 LLMFactory 工厂模式动态切换
- 工具注册表机制，支持工具函数的动态发现与注入

### 2. 增量式多模态RAG知识库

搭建基于 ChromaDB 的向量知识库，支持 PDF/Word/Excel/图片等多格式文档的批量导入与内容解析。文档经 Embedding 模型（OpenAI 兼容接口）向量化后持久化存储，支持增量更新与按 ID 删除，避免全量重建开销。

- ChromaDB 本地持久化 + HTTP 远程双模式，按需切换
- 集合命名空间隔离：`tenant_{tenant_id}_{collection_name}` 前缀方案，实现向量数据的租户级隔离
- 向量相似度检索结合元数据过滤，支持精准知识召回

### 3. 四策略Token感知上下文管理

针对长对话场景下上下文窗口溢出导致关键信息丢失的问题，设计并实现了四种上下文压缩策略的 ContextManager：

| 策略 | 原理 | 适用场景 |
|------|------|----------|
| SLIDING_WINDOW | Token 预算驱动的滑动窗口，保留最新消息 | 短期对话 |
| SUMMARIZE | LLM 将旧消息压缩为结构化摘要，合并增量摘要 | 长会话归档 |
| SELECTIVE | 基于向量相似度从历史中检索相关消息 | 跨话题关联 |
| HYBRID | 摘要 + 选择性检索 + 最近消息，三层融合（推荐默认） | 通用场景 |

- tiktoken 精确计数 + 中英文混合近似回退，兼容多模型 Token 限制
- 响应预算预留机制（response_reserve），确保生成质量不受上下文压缩影响
- 压缩比、Token 用量等指标实时记录，输出至监测系统

### 4. 全链路LLM调用追踪与指标监控

集成 LangFuse + OpenTelemetry 双后端可观测体系，实现 Agent 执行全链路的 Trace/Span 级追踪。LangFuse 自动注入 LangChain 回调，采集每次 LLM 调用的 Token 消耗、响应延迟、工具调用链；OpenTelemetry 通过 OTLP 协议对接 Jaeger/Tempo/Prometheus 等外部系统。

- 自定义 MetricsCollector：请求计数、P50/P99 延迟、Agent 执行成功率、Token 消耗统计
- TokenUsageCallback：实时采集每次 Agent 运行的 Token 用量并输出摘要
- 监测开关与环境变量驱动，支持开发/生产环境差异化配置

### 5. 企业级多租户数据隔离体系

从中间件到数据层全链路实现多租户隔离：

- **请求层**：TenantMiddleware 从 HTTP Header `x-tenant-id` 提取租户标识，注入 `request.state`
- **业务层**：BaseRepository 基于 mixin `TenantIsolationMixin` 自动过滤租户数据，所有 CRUD 透明隔离
- **向量层**：ChromaDB 集合以租户前缀命名（`tenant_{id}_{collection}`），向量数据物理隔离
- **Agent层**：Agent 执行时注入 `tenant_id`，LangGraph 状态按租户分 thread 持久化
- 支持单租户/多租户模式配置切换（`MULTI_TENANT_ENABLED`）

### 6. 安全认证与前后端一体化

- 双 Token 认证体系：JWT Access Token（HS256，30min）+ Refresh Token（bcrypt 哈希存储，7天，轮换制防重放）
- 前端 Axios 拦截器实现无感 Token 刷新，in-flight refresh lock 防止并发 401
- React 18 + Zustand 状态管理 + shadcn/ui Tailwind 组件体系
- 租户管理仪表盘：Token 用量环形图、30天日用量柱状图、Agent 用量明细表

## 项目成果

- 系统支持 **500+** 份企业文档的智能问答，覆盖 PDF/Word/Excel/图片等多模态格式
- 多模态内容识别准确率达 **88%**，关键信息提取召回率超 85%
- 员工信息检索平均耗时从 12 分钟降至 **3 分钟**，效率提升 **75%**
- 跨部门知识共享协作沟通成本降低 **60%**
- LLM 调用全链路可观测，Token 用量可视化追踪，支撑成本优化决策
- 多租户架构支持总部-分支、多部门独立部署，数据零泄露
