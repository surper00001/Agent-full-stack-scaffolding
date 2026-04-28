import { TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { TokenGauge } from "@/components/common/token-gauge";
import { BarChart } from "@/components/common/bar-chart";
import type { TokenUsage } from "@/types";

interface Props {
  usage: TokenUsage;
}

export function TokenUsageSection({ usage }: Props) {
  const trend = usage.comparedToLastMonth;
  const isUp = trend >= 0;

  const chartData = usage.dailyUsage.map((d) => ({
    label: d.date.slice(5),
    value: d.count,
  }));

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* 左侧 — 环形仪表盘 */}
      <Card className="animate-fade-in-up" style={{ animationDelay: "320ms", animationFillMode: "backwards" }}>
        <CardHeader>
          <CardTitle className="text-base">本月用量概览</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center pb-6">
          <TokenGauge used={usage.used} quota={usage.quota} />
          <div className="flex items-center gap-1.5 mt-3 text-sm">
            <span className="text-muted-foreground">较上月</span>
            {isUp ? (
              <span className="flex items-center gap-0.5 text-chart-2 font-medium">
                <TrendingUp className="h-3.5 w-3.5" />+{trend}%
              </span>
            ) : (
              <span className="flex items-center gap-0.5 text-chart-5 font-medium">
                <TrendingDown className="h-3.5 w-3.5" />
                {trend}%
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* 右侧 — 30天柱状图 */}
      <Card className="animate-fade-in-up" style={{ animationDelay: "400ms", animationFillMode: "backwards" }}>
        <CardHeader>
          <CardTitle className="text-base">近 30 天日用量</CardTitle>
        </CardHeader>
        <CardContent>
          <BarChart data={chartData} height={140} />
        </CardContent>
      </Card>
    </div>
  );
}
