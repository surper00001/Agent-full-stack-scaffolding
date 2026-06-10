import { useParams, Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAgent } from "@/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { CostBadge } from "@/components/common/cost-badge";
import { formatCost } from "@/lib/cost";
import {
  ArrowLeft, Settings, MessageSquare, Activity, Clock,
  CheckCircle2, XCircle, Zap, Hash, DollarSign,
  BarChart3, TrendingUp, AlertTriangle,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
  AreaChart, Area,
} from "recharts";
import * as obsApi from "@/api/observability";
import type {
  SingleAgentAnalytics,
  LatencyPoint,
  DailyExecution,
  DailyTokens,
  DailyCost,
  RecentExecution,
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

// ── Stat card helper ──

function StatCard({
  label, value, sub, icon: Icon, color,
}: {
  label: string; value: string; sub: string;
  icon: React.ComponentType<{ className?: string }>; color: string;
}) {
  return (
    <Card className="border-l-4" style={{ borderLeftColor: color }}>
      <CardContent className="p-4 flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-xl font-bold" style={{ color }}>{value}</p>
          <p className="text-[10px] text-muted-foreground">{sub}</p>
        </div>
        <Icon className="h-7 w-7 opacity-20" style={{ color }} />
      </CardContent>
    </Card>
  );
}

// ── Main page ──

export default function AdminAgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { agent, isLoading: agentLoading } = useAgent(id);

  const [analytics, setAnalytics] = useState<SingleAgentAnalytics | null>(null);
  const [dailyExec, setDailyExec] = useState<DailyExecution[]>([]);
  const [dailyTokens, setDailyTokens] = useState<DailyTokens[]>([]);
  const [dailyCost, setDailyCost] = useState<DailyCost[]>([]);
  const [latencyTrend, setLatencyTrend] = useState<LatencyPoint[]>([]);
  const [recentExecs, setRecentExecs] = useState<RecentExecution[]>([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [dataError, setDataError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    async function load() {
      try {
        const [a, exec, tokens, cost, latency, recent] = await Promise.all([
          obsApi.getSingleAgentAnalytics(id!),
          obsApi.getAgentDailyExecutions(id!, 7),
          obsApi.getAgentDailyTokens(id!, 7),
          obsApi.getAgentDailyCost(id!, 7),
          obsApi.getLatencyTimeSeries(24),
          obsApi.getAgentRecentExecutions(id!, 10),
        ]);
        if (cancelled) return;
        setAnalytics(a);
        setDailyExec(exec);
        setDailyTokens(tokens);
        setDailyCost(cost);
        setLatencyTrend(latency);
        setRecentExecs(recent);
      } catch (err: unknown) {
        if (!cancelled) {
          setDataError(err instanceof Error ? err.message : "加载失败");
        }
      } finally {
        if (!cancelled) setDataLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [id]);

  const isLoading = agentLoading || dataLoading;

  // 计算汇总
  const totalExec = analytics?.executions ?? 0;
  const failureCount = analytics?.failure_count ?? 0;
  const successRate = analytics?.success_rate ?? 0;
  const avgLatency = analytics?.avg_latency_ms ?? 0;
  const totalTokens = analytics?.total_tokens ?? 0;
  const totalCost = dailyCost.reduce((s, d) => s + d.cost, 0);

  if (isLoading) return <LoadingSpinner size="lg" className="mt-24" />;

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <p className="text-lg text-muted-foreground">Agent不存在</p>
        <Link to="/admin/agents" className="mt-4">
          <Button variant="outline"><ArrowLeft className="mr-2 h-4 w-4" />返回列表</Button>
        </Link>
      </div>
    );
  }

  if (dataError) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-muted-foreground">
        <AlertTriangle className="h-10 w-10 text-amber-500 mb-3" />
        <p className="text-lg">数据加载失败</p>
        <p className="text-sm mt-1">{dataError}</p>
        <Link to={`/admin/agents/${id}`} className="mt-4">
          <Button variant="outline">重试</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/admin/agents">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">{agent.name}</h1>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="px-1.5 py-0.5 rounded bg-muted text-[11px] font-medium">
              {agent.agent_type}
            </span>
            <span>·</span>
            <span>{agent.model_name}</span>
            <span>·</span>
            <span className={agent.is_active ? "text-emerald-600" : "text-muted-foreground"}>
              {agent.is_active ? "● 启用" : "○ 禁用"}
            </span>
          </div>
        </div>
        <CostBadge cost={totalCost} size="md" />
      </div>

      {/* Performance Stats Row */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          label="总执行次数"
          value={totalExec.toLocaleString()}
          sub="最近7天"
          icon={Activity}
          color="#3b82f6"
        />
        <StatCard
          label="成功率"
          value={`${successRate.toFixed(1)}%`}
          sub={`${failureCount} 失败`}
          icon={CheckCircle2}
          color={successRate > 95 ? "#10b981" : successRate > 85 ? "#f59e0b" : "#ef4444"}
        />
        <StatCard
          label="平均延迟"
          value={fmtLatency(avgLatency)}
          sub="P95: 见延迟趋势图"
          icon={Clock}
          color="#8b5cf6"
        />
        <StatCard
          label="Token 消耗"
          value={fmtTokens(totalTokens)}
          sub="7天合计"
          icon={Hash}
          color="#06b6d4"
        />
        <StatCard
          label="累计费用"
          value={formatCost(totalCost)}
          sub={`日均 ${formatCost(totalCost / Math.max(1, dailyCost.filter(d => d.cost > 0).length || 7))}`}
          icon={DollarSign}
          color="#f59e0b"
        />
      </div>

      {/* Config + System Prompt */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Settings className="h-4 w-4" />基础配置
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <InfoRow label="类型" value={agent.agent_type} />
            <InfoRow label="状态" value={agent.is_active ? "启用" : "禁用"} />
            <InfoRow label="模型" value={agent.model_name} />
            <InfoRow label="温度" value={String(agent.temperature)} />
            <InfoRow label="创建时间" value={new Date(agent.created_at).toLocaleString("zh-CN")} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MessageSquare className="h-4 w-4" />系统提示词
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap rounded-md bg-muted p-4 text-sm max-h-48 overflow-y-auto">
              {agent.system_prompt || "未设置系统提示词"}
            </pre>
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 1: Executions + Latency */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-blue-500" />
              每日执行统计
            </CardTitle>
          </CardHeader>
          <CardContent>
            {dailyExec.length === 0 ? (
              <div className="flex items-center justify-center h-[220px] text-sm text-muted-foreground">
                暂无执行数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={dailyExec} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="success" name="成功" fill="#10b981" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="failure" name="失败" fill="#ef4444" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="timeout" name="超时" fill="#f59e0b" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Clock className="h-4 w-4 text-purple-500" />
              延迟趋势 (24H)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {latencyTrend.length === 0 ? (
              <div className="flex items-center justify-center h-[220px] text-sm text-muted-foreground">
                暂无延迟数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={latencyTrend}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="time" tick={{ fontSize: 9 }} interval={3} />
                  <YAxis tick={{ fontSize: 10 }} unit="ms" />
                  <Tooltip />
                  <Legend />
                  <Area type="monotone" dataKey="p95" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.15} strokeWidth={2} name="P95" />
                  <Area type="monotone" dataKey="avg" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.1} strokeWidth={2} name="平均" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 2: Tokens + Tools (placeholder) */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-500" />
              Token 消耗趋势 (7天)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {dailyTokens.length === 0 ? (
              <div className="flex items-center justify-center h-[200px] text-sm text-muted-foreground">
                暂无 Token 数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={dailyTokens} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="prompt" name="Input" fill="#3b82f6" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="completion" name="Output" fill="#06b6d4" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-500" />
              工具使用分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-center h-[200px] text-sm text-muted-foreground">
              <p className="text-center">
                工具使用追踪功能<br />开发中，敬请期待
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 3: Cost Trend + Recent Executions */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <DollarSign className="h-4 w-4 text-amber-500" />
              费用趋势 (7天)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {dailyCost.length === 0 ? (
              <div className="flex items-center justify-center h-[180px] text-sm text-muted-foreground">
                暂无费用数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={dailyCost}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v.toFixed(2)}`} />
                  <Tooltip formatter={(value: number) => [formatCost(value), "费用"]} />
                  <Area
                    type="monotone"
                    dataKey="cost"
                    stroke="#f59e0b"
                    fill="#fde68a"
                    fillOpacity={0.5}
                    strokeWidth={2}
                    name="费用"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
            {totalCost > 0 && (
              <p className="text-center text-[10px] text-muted-foreground mt-1">
                7日合计: {formatCost(totalCost)} · 预估月费: {formatCost(totalCost * 4.3)}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Activity className="h-4 w-4 text-blue-500" />
              最近执行记录
            </CardTitle>
          </CardHeader>
          <CardContent>
            {recentExecs.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-8">
                暂无执行记录
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 font-medium">时间</th>
                      <th className="pb-2 font-medium">会话</th>
                      <th className="pb-2 font-medium">Tokens</th>
                      <th className="pb-2 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentExecs.map((row, i) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                        <td className="py-1.5 font-mono text-[10px]">{row.time}</td>
                        <td className="py-1.5 max-w-[120px] truncate">{row.title}</td>
                        <td className="py-1.5 font-mono text-[10px]">{fmtTokens(row.tokens)}</td>
                        <td className="py-1.5">
                          {row.status === "success" ? (
                            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                          ) : (
                            <XCircle className="h-3 w-3 text-amber-500" />
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
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
