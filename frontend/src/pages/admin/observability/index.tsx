import { useEffect, useState, useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import {
  Activity, Zap, Bot, Hash, Shield, CheckCircle2, AlertTriangle, Clock,
  XCircle,
} from "lucide-react";
import { formatCost } from "@/lib/cost";
import * as obsApi from "@/api/observability";
import type {
  ObservabilityOverview,
  LLMCallRecord,
  AgentAnalytics,
  LatencyPoint,
  TokenTrendPoint,
  AgentExecSummary,
} from "@/api/observability";

// ── 格式化辅助 ──

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtLatency(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

// ── 健康状态图标映射 ──

function HealthIcon({ status }: { status: string }) {
  switch (status) {
    case "healthy":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
    case "unhealthy":
      return <XCircle className="h-3.5 w-3.5 text-red-500" />;
    case "degraded":
      return <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />;
    default:
      return <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" />;
  }
}

// ── 主页面 ──

export default function ObservabilityDashboardPage() {
  const [overview, setOverview] = useState<ObservabilityOverview | null>(null);
  const [llmRecords, setLlmRecords] = useState<LLMCallRecord[]>([]);
  const [agentAnalytics, setAgentAnalytics] = useState<AgentAnalytics[]>([]);
  const [latencyData, setLatencyData] = useState<LatencyPoint[]>([]);
  const [tokenTrend, setTokenTrend] = useState<TokenTrendPoint[]>([]);
  const [agentExecData, setAgentExecData] = useState<AgentExecSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadAll() {
      try {
        const [ov, llm, agents, latency, tokens, execs] = await Promise.all([
          obsApi.getOverview(),
          obsApi.getRecentLLMCalls(20),
          obsApi.getAgentAnalytics(),
          obsApi.getLatencyTimeSeries(24),
          obsApi.getTokensTimeSeries(7),
          obsApi.getAgentExecTimeSeries(7),
        ]);
        if (cancelled) return;
        setOverview(ov);
        setLlmRecords(llm.records);
        setAgentAnalytics(agents);
        setLatencyData(latency);
        setTokenTrend(tokens);
        setAgentExecData(execs);
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "加载失败";
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadAll();
    return () => { cancelled = true; };
  }, []);

  // 计算汇总值
  const stats = useMemo(() => {
    const s = overview?.stats;
    return {
      requestsToday: s?.requests_today ?? 0,
      agentExecToday: s?.agent_executions_today ?? 0,
      successRate: s?.agent_success_rate ?? 0,
      llmCallsToday: s?.llm_calls_today ?? 0,
      avgLatency: s?.llm_avg_latency_ms ?? 0,
      tokensToday: s?.tokens_today ?? 0,
      totalCost: s?.total_cost ?? 0,
    };
  }, [overview]);

  if (loading) return <LoadingSpinner size="lg" className="mt-24" />;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-muted-foreground">
        <AlertTriangle className="h-10 w-10 text-amber-500 mb-3" />
        <p className="text-lg">数据加载失败</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Activity className="h-6 w-6 text-emerald-500" />
            可观测性大屏
          </h1>
          <p className="text-muted-foreground text-sm">
            LLM 调用追踪 · Agent 执行监控 · 系统健康状态 · 实时日志
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-full text-xs text-emerald-700 dark:text-emerald-300">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          实时监控中
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "今日活跃用户", value: stats.requestsToday.toLocaleString(), sub: "注册用户总数", icon: Activity, color: "text-blue-500" },
          { label: "Agent 执行", value: stats.agentExecToday.toLocaleString(), sub: `成功率 ${stats.successRate.toFixed(1)}%`, icon: Bot, color: "text-emerald-500" },
          { label: "LLM 调用", value: stats.llmCallsToday.toLocaleString(), sub: `平均延迟 ${fmtLatency(stats.avgLatency)}`, icon: Zap, color: "text-amber-500" },
          { label: "Token 消耗", value: fmtTokens(stats.tokensToday), sub: `预估 ${formatCost(stats.totalCost)}`, icon: Hash, color: "text-purple-500" },
        ].map(({ label, value, sub, icon: Icon, color }) => (
          <Card key={label} className="border-l-4 border-l-current">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">{label}</p>
                  <p className={`text-2xl font-bold ${color}`}>{value}</p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>
                </div>
                <Icon className={`h-8 w-8 ${color} opacity-30`} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Charts Row 1: Latency + Agent Executions */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Latency Distribution */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Clock className="h-4 w-4 text-blue-500" />
              LLM 调用延迟趋势 (24H)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {latencyData.length === 0 ? (
              <div className="flex items-center justify-center h-[250px] text-sm text-muted-foreground">
                暂无延迟数据（等待 LLM 调用后生成）
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={latencyData}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="time" tick={{ fontSize: 10 }} interval={3} />
                  <YAxis tick={{ fontSize: 10 }} unit="ms" />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="avg" stroke="#3b82f6" strokeWidth={2} dot={false} name="平均延迟" />
                  <Line type="monotone" dataKey="p95" stroke="#ef4444" strokeWidth={2} dot={false} name="P95" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Agent Executions */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Bot className="h-4 w-4 text-emerald-500" />
              Agent 执行统计
            </CardTitle>
          </CardHeader>
          <CardContent>
            {agentExecData.length === 0 ? (
              <div className="flex items-center justify-center h-[250px] text-sm text-muted-foreground">
                暂无 Agent 执行数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={agentExecData} barGap={4}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="success" fill="#10b981" radius={[2, 2, 0, 0]} name="成功" />
                  <Bar dataKey="failure" fill="#ef4444" radius={[2, 2, 0, 0]} name="失败" />
                  <Bar dataKey="timeout" fill="#f59e0b" radius={[2, 2, 0, 0]} name="超时" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 2: Token Trend + System Health */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Token Trend */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Hash className="h-4 w-4 text-purple-500" />
              Token 消耗趋势 (7天)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {tokenTrend.length === 0 ? (
              <div className="flex items-center justify-center h-[220px] text-sm text-muted-foreground">
                暂无 Token 消耗数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={tokenTrend}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend />
                  <Area type="monotone" dataKey="input" stackId="1" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.3} name="Input Tokens" />
                  <Area type="monotone" dataKey="output" stackId="1" stroke="#06b6d4" fill="#06b6d4" fillOpacity={0.3} name="Output Tokens" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* System Health */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Shield className="h-4 w-4 text-emerald-500" />
              系统健康状态
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {overview?.health && overview.health.length > 0 ? (
              overview.health.map((item) => (
                <div key={item.name} className="flex items-center justify-between py-1.5 border-b last:border-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium">{item.name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground">{item.detail}</span>
                    <HealthIcon status={item.status} />
                  </div>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground text-center py-4">暂无健康检查数据</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Live LLM Call Log + Agent Performance */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* LLM Call Log */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              实时 LLM 调用日志
            </CardTitle>
          </CardHeader>
          <CardContent>
            {llmRecords.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-8">
                暂无 LLM 调用记录（开始使用 Agent 后将自动出现）
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 font-medium">时间</th>
                      <th className="pb-2 font-medium">节点</th>
                      <th className="pb-2 font-medium">模型</th>
                      <th className="pb-2 font-medium">延迟</th>
                      <th className="pb-2 font-medium">Tokens</th>
                      <th className="pb-2 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {llmRecords.map((log, i) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                        <td className="py-1.5 font-mono text-[10px]">{log.time}</td>
                        <td className="py-1.5">
                          <span className="px-1.5 py-0.5 rounded bg-muted text-[10px] font-medium">
                            {log.node}
                          </span>
                        </td>
                        <td className="py-1.5 text-[10px]">{log.model}</td>
                        <td className="py-1.5 font-mono text-[10px]">{log.latency_display}</td>
                        <td className="py-1.5 font-mono text-[10px]">{log.tokens_display}</td>
                        <td className="py-1.5">
                          {log.status === "success" ? (
                            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                          ) : (
                            <AlertTriangle className="h-3 w-3 text-amber-500" />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Agent Performance Table */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Bot className="h-4 w-4 text-blue-500" />
              Agent 性能概览
            </CardTitle>
          </CardHeader>
          <CardContent>
            {agentAnalytics.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-8">
                暂无 Agent 数据
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 font-medium">Agent</th>
                      <th className="pb-2 font-medium text-right">执行</th>
                      <th className="pb-2 font-medium text-right">成功率</th>
                      <th className="pb-2 font-medium text-right">平均延迟</th>
                      <th className="pb-2 font-medium text-right">Tokens</th>
                      <th className="pb-2 font-medium text-right">费用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentAnalytics.map((agent, i) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                        <td className="py-2 font-medium">{agent.name}</td>
                        <td className="py-2 text-right font-mono">{agent.executions.toLocaleString()}</td>
                        <td className="py-2 text-right">
                          <span className="text-emerald-600 font-mono">{agent.success_rate}%</span>
                        </td>
                        <td className="py-2 text-right font-mono">{fmtLatency(agent.avg_latency_ms)}</td>
                        <td className="py-2 text-right font-mono">{fmtTokens(agent.total_tokens)}</td>
                        <td className="py-2 text-right font-mono text-amber-600">{formatCost(agent.total_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Footer note */}
      <p className="text-center text-[10px] text-muted-foreground">
        数据每 30s 自动刷新 · 追踪后端: Langfuse + OpenTelemetry · 指标: Prometheus · 日志: Loguru
      </p>
    </div>
  );
}
