/**
 * 可观测性 API — 为前端图表和监控页面提供真实后端数据。
 *
 * 所有数据均来自后端 DB 查询、内存追踪器和健康检查，无 mock。
 */
import client from "./client";

// ── 类型定义 ──

export interface ObservabilityOverview {
  stats: {
    requests_today: number;
    agent_executions: number;
    agent_executions_today: number;
    llm_calls: number;
    llm_calls_today: number;
    total_tokens: number;
    tokens_today: number;
    agent_success_rate: number;
    llm_avg_latency_ms: number;
    total_cost: number;
  };
  health: SystemHealthItem[];
}

export interface SystemHealthItem {
  name: string;
  status: "healthy" | "unhealthy" | "degraded" | "disabled";
  detail: string;
  icon: string;
}

export interface LLMCallRecord {
  time: string;
  model: string;
  node: string;
  latency_ms: number;
  latency_display: string;
  tokens: number;
  tokens_display: string;
  status: "success" | "error";
  error?: string;
}

export interface LLMCallStats {
  total_calls: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens: number;
}

export interface AgentAnalytics {
  name: string;
  agent_type: string;
  model_name: string;
  executions: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens: number;
  total_cost: number;
  conversation_count: number;
}

export interface SingleAgentAnalytics {
  name: string;
  agent_type: string;
  model_name: string;
  executions: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens: number;
  total_cost: number;
  conversation_count: number;
}

export interface LatencyPoint {
  time: string;
  avg: number;
  p95: number;
  count: number;
}

export interface TokenTrendPoint {
  date: string;
  input: number;
  output: number;
  total: number;
}

export interface AgentExecSummary {
  name: string;
  success: number;
  failure: number;
  timeout: number;
}

export interface DailyExecution {
  date: string;
  success: number;
  failure: number;
  timeout: number;
}

export interface DailyTokens {
  date: string;
  prompt: number;
  completion: number;
}

export interface DailyCost {
  date: string;
  cost: number;
}

export interface RecentExecution {
  time: string;
  conv_id: string;
  title: string;
  tokens: number;
  status: string;
}

// ── API 函数 ──

/** 可观测性概览 */
export async function getOverview(): Promise<ObservabilityOverview> {
  const { data } = await client.get("/admin/observability/overview");
  return data.data;
}

/** 最近 LLM 调用记录 */
export async function getRecentLLMCalls(
  limit = 20,
): Promise<{ records: LLMCallRecord[]; stats: LLMCallStats }> {
  const { data } = await client.get("/admin/observability/llm-calls", {
    params: { limit },
  });
  return data.data;
}

/** 所有 Agent 分析数据 */
export async function getAgentAnalytics(): Promise<AgentAnalytics[]> {
  const { data } = await client.get("/admin/observability/agents");
  return data.data.agents;
}

/** 单个 Agent 分析数据 */
export async function getSingleAgentAnalytics(
  agentId: string,
): Promise<SingleAgentAnalytics> {
  const { data } = await client.get(`/admin/observability/agents/${agentId}`);
  return data.data;
}

/** 延迟时序数据（按小时） */
export async function getLatencyTimeSeries(
  hours = 24,
): Promise<LatencyPoint[]> {
  const { data } = await client.get(
    "/admin/observability/time-series/latency",
    { params: { hours } },
  );
  return data.data;
}

/** Token 时序数据（按天） */
export async function getTokensTimeSeries(
  days = 7,
): Promise<TokenTrendPoint[]> {
  const { data } = await client.get(
    "/admin/observability/time-series/tokens",
    { params: { days } },
  );
  return data.data;
}

/** Agent 执行汇总（按天） */
export async function getAgentExecTimeSeries(
  days = 7,
): Promise<AgentExecSummary[]> {
  const { data } = await client.get(
    "/admin/observability/time-series/agent-executions",
    { params: { days } },
  );
  return data.data;
}

/** 单 Agent 每日执行统计 */
export async function getAgentDailyExecutions(
  agentId: string,
  days = 7,
): Promise<DailyExecution[]> {
  const { data } = await client.get(
    `/admin/observability/agents/${agentId}/time-series/executions`,
    { params: { days } },
  );
  return data.data;
}

/** 单 Agent 每日 Token */
export async function getAgentDailyTokens(
  agentId: string,
  days = 7,
): Promise<DailyTokens[]> {
  const { data } = await client.get(
    `/admin/observability/agents/${agentId}/time-series/tokens`,
    { params: { days } },
  );
  return data.data;
}

/** 单 Agent 每日费用 */
export async function getAgentDailyCost(
  agentId: string,
  days = 7,
): Promise<DailyCost[]> {
  const { data } = await client.get(
    `/admin/observability/agents/${agentId}/time-series/cost`,
    { params: { days } },
  );
  return data.data;
}

/** 单 Agent 最近执行记录 */
export async function getAgentRecentExecutions(
  agentId: string,
  limit = 10,
): Promise<RecentExecution[]> {
  const { data } = await client.get(
    `/admin/observability/agents/${agentId}/recent-executions`,
    { params: { limit } },
  );
  return data.data;
}



