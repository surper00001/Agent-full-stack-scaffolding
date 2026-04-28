import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useAgentStore } from "@/stores";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { Bot, MessageSquare, Activity } from "lucide-react";

export default function DashboardPage() {
  const { agents, isLoading, fetchAgents } = useAgentStore();

  useEffect(() => {
    fetchAgents(1, 100);
  }, [fetchAgents]);

  if (isLoading) return <LoadingSpinner size="lg" className="mt-24" />;

  const activeAgents = agents.filter((a) => a.is_active).length;

  const stats = [
    { label: "Agent总数", value: agents.length, icon: Bot, href: "/agents" },
    { label: "活跃Agent", value: activeAgents, icon: Activity, href: "/agents" },
    { label: "对话记录", value: "--", icon: MessageSquare, href: "/conversations" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">仪表盘</h1>
        <p className="text-muted-foreground">AI Agent 平台运行概览</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map(({ label, value, icon: Icon, href }) => (
          <Link key={label} to={href}>
            <Card className="transition-shadow hover:shadow-md">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">{label}</CardTitle>
                <Icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{value}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle className="text-lg">Agent 列表</CardTitle></CardHeader>
        <CardContent>
          {agents.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              暂无Agent，请前往
              <Link to="/agents" className="mx-1 text-primary hover:underline">Agent管理</Link>
              创建
            </p>
          ) : (
            <div className="space-y-2">
              {agents.slice(0, 5).map((agent) => (
                <Link key={agent.id} to={`/agents/${agent.id}`} className="flex items-center justify-between rounded-md border p-3 transition-colors hover:bg-accent">
                  <div>
                    <p className="font-medium">{agent.name}</p>
                    <p className="text-sm text-muted-foreground">{agent.agent_type}</p>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-xs ${agent.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                    {agent.is_active ? "启用" : "禁用"}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
