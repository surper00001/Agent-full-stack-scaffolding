import { Activity, TrendingUp, Timer, Star, Target } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface MetricsCardProps {
  usageCount: number;
  successCount: number;
  avgDurationMs?: number | null;
  avgRating?: number | null;
  isConcurrencySafe?: boolean;
}

export function MetricsCard({
  usageCount,
  successCount,
  avgDurationMs,
  avgRating,
  isConcurrencySafe,
}: MetricsCardProps) {
  const successRate = usageCount > 0 ? Math.round((successCount / usageCount) * 100) : 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Activity className="w-4 h-4 text-purple-500" />
          运行指标
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 调用次数 + 成功率 */}
        <div className="grid grid-cols-2 gap-3">
          <div className="text-center p-2 rounded-lg bg-muted/50">
            <div className="text-lg font-bold text-foreground">
              {usageCount.toLocaleString()}
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5">总调用</div>
          </div>
          <div className="text-center p-2 rounded-lg bg-muted/50">
            <div
              className={cn(
                "text-lg font-bold",
                successRate >= 95 ? "text-green-600" : successRate >= 80 ? "text-yellow-600" : "text-red-600"
              )}
            >
              {successRate}%
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5">成功率</div>
          </div>
        </div>

        {/* 成功率进度条 */}
        <div className="space-y-0.5">
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                successRate >= 95 ? "bg-green-400" : successRate >= 80 ? "bg-yellow-400" : "bg-red-400"
              )}
              style={{ width: `${successRate}%` }}
            />
          </div>
        </div>

        {/* 平均耗时 */}
        <div className="flex items-center gap-2 text-xs">
          <Timer className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-muted-foreground">平均耗时</span>
          <span className="ml-auto font-mono text-[11px]">
            {avgDurationMs ? `${avgDurationMs.toFixed(1)} ms` : "-"}
          </span>
        </div>

        {/* 评分 */}
        <div className="flex items-center gap-2 text-xs">
          <Star className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-muted-foreground">用户评分</span>
          <span className="ml-auto font-mono text-[11px]">
            {avgRating ? `★ ${avgRating.toFixed(1)}` : "暂无"}
          </span>
        </div>

        {/* 并发安全 */}
        <div className="flex items-center gap-2 text-xs">
          <Target className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-muted-foreground">并发安全</span>
          <span
            className={cn(
              "ml-auto text-[11px] font-medium px-1.5 py-0.5 rounded",
              isConcurrencySafe
                ? "bg-green-50 text-green-600"
                : "bg-gray-100 text-gray-500"
            )}
          >
            {isConcurrencySafe ? "✅ 是" : "❌ 否"}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
