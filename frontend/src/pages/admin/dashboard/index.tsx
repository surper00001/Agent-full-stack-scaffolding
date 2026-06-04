import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { getSkills } from "@/api/skills";
import {
  Bot,
  MessageSquare,
  Users,
  Zap,
  TrendingUp,
  Activity,
  Shield,
  Container,
  Play,
  Code2,
} from "lucide-react";
import type { AdminStats } from "@/api/admin";
import * as adminApi from "@/api/admin";
import type { Skill } from "@/types/skill";

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [skills, setSkills] = useState<Skill[]>([]);

  useEffect(() => {
    Promise.all([
      adminApi.getAdminStats(),
      getSkills({ page: 1, page_size: 100 }).catch(() => ({ data: { items: [] as Skill[], total: 0 } })),
    ])
      .then(([statsRes, skillsRes]) => {
        setStats(statsRes.data);
        setSkills(skillsRes.data.items);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner size="lg" className="mt-24" />;

  // Harness 统计
  const activeSkills = skills.filter((s) => s.status === "active");
  const publishedSkills = skills.filter((s) => s.status === "published");
  const testingSkills = skills.filter((s) => s.status === "testing");
  const draftSkills = skills.filter((s) => s.status === "draft");
  const sandboxedSkills = skills.filter((s) => s.requires_sandbox);

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

      {/* ── Harness 工程概览 ── */}
      {skills.length > 0 && (
        <Card className="border-l-4 border-l-emerald-500">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Zap className="w-5 h-5 text-emerald-500" />
              Harness 工程 · Skill 运行状态
            </CardTitle>
            <Link
              to="/admin/skills"
              className="text-sm text-emerald-600 hover:text-emerald-700 font-medium"
            >
              管理 Skills →
            </Link>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
              <HarnessStat
                icon={Play}
                label="已激活"
                value={activeSkills.length}
                color="bg-emerald-50 text-emerald-700 border-emerald-200"
              />
              <HarnessStat
                icon={Code2}
                label="已发布"
                value={publishedSkills.length}
                color="bg-indigo-50 text-indigo-700 border-indigo-200"
              />
              <HarnessStat
                icon={Activity}
                label="测试中"
                value={testingSkills.length}
                color="bg-blue-50 text-blue-700 border-blue-200"
              />
              <HarnessStat
                icon={Code2}
                label="草稿"
                value={draftSkills.length}
                color="bg-gray-50 text-gray-600 border-gray-200"
              />
              <HarnessStat
                icon={Container}
                label="沙箱隔离"
                value={sandboxedSkills.length}
                color="bg-purple-50 text-purple-700 border-purple-200"
              />
              <HarnessStat
                icon={Shield}
                label="总 Skills"
                value={skills.length}
                color="bg-amber-50 text-amber-700 border-amber-200"
              />
            </div>
            {/* 状态分布条 */}
            {skills.length > 0 && (
              <div className="mt-4">
                <div className="flex h-2 rounded-full overflow-hidden">
                  {[
                    { count: activeSkills.length, color: "bg-emerald-400" },
                    { count: publishedSkills.length, color: "bg-indigo-400" },
                    { count: testingSkills.length, color: "bg-blue-400" },
                    { count: draftSkills.length, color: "bg-gray-300" },
                  ]
                    .filter((s) => s.count > 0)
                    .map((s, i) => (
                      <div
                        key={i}
                        className={s.color}
                        style={{
                          width: `${(s.count / skills.length) * 100}%`,
                        }}
                      />
                    ))}
                </div>
                <div className="flex justify-between mt-1 text-[10px] text-muted-foreground">
                  <span>草稿/测试 → 发布 → 激活</span>
                  <span>生命周期管道</span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 快速入口 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">快速入口</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {[
              { label: "用户管理", desc: "查看和管理系统用户", to: "/admin/users", icon: Users },
              { label: "对话记录", desc: "浏览所有用户对话", to: "/admin/conversations", icon: MessageSquare },
              { label: "租户管理", desc: "Token 用量与配额", to: "/admin/tenant", icon: TrendingUp },
              { label: "Agent 管理", desc: "配置智能体参数", to: "/admin/agents", icon: Bot },
              { label: "Skill 管理", desc: "AI 能力单元管理", to: "/admin/skills", icon: Zap },
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

// ── Harness 统计小卡片 ──
function HarnessStat({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className={`flex items-center gap-3 p-3 rounded-lg border ${color}`}>
      <Icon className="w-5 h-5 shrink-0" />
      <div>
        <div className="text-lg font-bold">{value}</div>
        <div className="text-[11px] opacity-70">{label}</div>
      </div>
    </div>
  );
}
