import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { Bot, MessageSquare, Users, Zap, TrendingUp, Activity } from "lucide-react";
import type { AdminStats } from "@/api/admin";
import * as adminApi from "@/api/admin";

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminApi
      .getAdminStats()
      .then((res) => setStats(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner size="lg" className="mt-24" />;

  const statCards = [
    {
      label: "用户总数",
      value: stats?.total_users ?? "--",
      icon: Users,
      href: "/admin/users",
      color: "text-blue-600",
    },
    {
      label: "对话总数",
      value: stats?.total_conversations ?? "--",
      icon: MessageSquare,
      href: "/admin/conversations",
      color: "text-green-600",
    },
    {
      label: "今日活跃用户",
      value: stats?.active_users_today ?? "--",
      icon: Activity,
      href: "/admin/users",
      color: "text-purple-600",
    },
    {
      label: "Token 总消耗",
      value: stats?.total_tokens != null ? stats.total_tokens.toLocaleString() : "--",
      icon: Zap,
      href: "/admin/tenant",
      color: "text-amber-600",
    },
    {
      label: "今日 Token",
      value: stats?.tokens_today != null ? stats.tokens_today.toLocaleString() : "--",
      icon: TrendingUp,
      href: "/admin/tenant",
      color: "text-rose-600",
    },
    {
      label: "消息总数",
      value: stats?.total_messages ?? "--",
      icon: MessageSquare,
      href: "/admin/conversations",
      color: "text-teal-600",
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">仪表盘</h1>
        <p className="text-muted-foreground">ClipFlow AI 智能工作台运行概览</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {statCards.map(({ label, value, icon: Icon, href, color }) => (
          <Link key={label} to={href}>
            <Card className="transition-shadow hover:shadow-md">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">{label}</CardTitle>
                <Icon className={`h-4 w-4 ${color}`} />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{value}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* 快速入口 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">快速入口</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: "用户管理", desc: "查看和管理系统用户", to: "/admin/users", icon: Users },
              { label: "对话记录", desc: "浏览所有用户对话", to: "/admin/conversations", icon: MessageSquare },
              { label: "租户管理", desc: "Token 用量与配额", to: "/admin/tenant", icon: TrendingUp },
              { label: "Agent 管理", desc: "配置智能体参数", to: "/admin/agents", icon: Bot },
            ].map(({ label, desc, to, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                className="flex items-start gap-3 rounded-lg border p-4 transition-colors hover:bg-accent"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-sm">{label}</p>
                  <p className="text-xs text-muted-foreground">{desc}</p>
                </div>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
