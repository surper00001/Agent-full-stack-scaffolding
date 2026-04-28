import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { AgentUsage } from "@/types";

interface Props {
  data: AgentUsage[];
}

export function UsageByAgent({ data }: Props) {
  if (data.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Agent 用量分布</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">暂无数据</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="animate-fade-in-up" style={{ animationDelay: "480ms", animationFillMode: "backwards" }}>
      <CardHeader>
        <CardTitle className="text-base">Agent 用量分布</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.map((item) => (
          <AgentRow key={item.agentName} item={item} />
        ))}
      </CardContent>
    </Card>
  );
}

function AgentRow({ item }: { item: AgentUsage }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium truncate mr-2">{item.agentName}</span>
        <span className="text-muted-foreground shrink-0">
          {item.count.toLocaleString()} tokens
        </span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${item.percentage}%`,
            backgroundColor: `var(--chart-${(Math.floor(item.percentage / 20) % 5) + 1})`,
          }}
        />
      </div>
      <p className="text-xs text-muted-foreground text-right">{item.percentage}%</p>
    </div>
  );
}
