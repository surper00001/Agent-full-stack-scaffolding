import { Building2, Users, BadgeCheck, Calendar } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { Tenant } from "@/types";

const PLAN_LABELS: Record<string, string> = {
  free: "免费版",
  pro: "专业版",
  enterprise: "企业版",
};

interface Props {
  tenant: Tenant;
  delay?: number;
}

export function TenantInfoCards({ tenant, delay = 0 }: Props) {
  const cards = buildCards(tenant);

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card, i) => (
        <Card
          key={card.label}
          className="animate-fade-in-up transition-shadow hover:shadow-md"
          style={{ animationDelay: `${delay + i * 80}ms`, animationFillMode: "backwards" }}
        >
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {card.label}
            </CardTitle>
            <card.icon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{card.value}</div>
            {card.sub && (
              <p className="text-xs text-muted-foreground mt-1">{card.sub}</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function buildCards(tenant: Tenant) {
  return [
    {
      label: "租户名称",
      value: tenant.name,
      sub: `ID: ${tenant.id.slice(0, 8)}...`,
      icon: Building2,
    },
    {
      label: "成员数量",
      value: tenant.memberCount,
      sub: "活跃用户",
      icon: Users,
    },
    {
      label: "套餐计划",
      value: PLAN_LABELS[tenant.plan] || tenant.plan,
      sub: tenant.plan === "enterprise" ? "无限制访问" : "按量计费",
      icon: BadgeCheck,
    },
    {
      label: "创建时间",
      value: formatDate(tenant.createdAt),
      sub: tenant.status === "active" ? "● 运行中" : "● 已暂停",
      icon: Calendar,
    },
  ];
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "--";
  return new Date(dateStr).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}
