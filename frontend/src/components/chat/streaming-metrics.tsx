import { Clock, Zap, Hash, Gauge, DollarSign } from "lucide-react";
import type { StreamTiming } from "@/types";
import { formatCost } from "@/lib/cost";

interface StreamingMetricsProps {
  timing: StreamTiming | null;
  tokenUsage?: {
    total_tokens?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    total_cost?: number;
  } | null;
  isStreaming?: boolean;
}

export function StreamingMetrics({ timing, tokenUsage, isStreaming }: StreamingMetricsProps) {
  if (!timing && !tokenUsage) return null;

  const elapsedS = timing ? (timing.elapsed_ms / 1000) : 0;
  const tps = timing?.tokens_per_second ?? (
    tokenUsage?.total_tokens && elapsedS > 0 ? tokenUsage.total_tokens / elapsedS : 0
  );

  const metrics: { icon: React.ReactNode; label: string; value: string }[] = [];

  if (timing?.ttft_ms != null) {
    metrics.push({
      icon: <Zap className="h-3 w-3" />,
      label: "TTFT",
      value: `${(timing.ttft_ms / 1000).toFixed(1)}s`,
    });
  }

  if (tps > 0) {
    metrics.push({
      icon: <Gauge className="h-3 w-3" />,
      label: "TPS",
      value: `${tps.toFixed(0)} tok/s`,
    });
  }

  if (timing?.elapsed_ms != null) {
    metrics.push({
      icon: <Clock className="h-3 w-3" />,
      label: "耗时",
      value: elapsedS >= 60
        ? `${Math.floor(elapsedS / 60)}m ${Math.floor(elapsedS % 60)}s`
        : `${elapsedS.toFixed(1)}s`,
    });
  }

  if (tokenUsage?.total_tokens != null) {
    metrics.push({
      icon: <Hash className="h-3 w-3" />,
      label: "Tokens",
      value: tokenUsage.total_tokens >= 1000
        ? `${(tokenUsage.total_tokens / 1000).toFixed(1)}K`
        : String(tokenUsage.total_tokens),
    });
  }

  if (tokenUsage?.total_cost != null && tokenUsage.total_cost > 0) {
    metrics.push({
      icon: <DollarSign className="h-3 w-3" />,
      label: "费用",
      value: formatCost(tokenUsage.total_cost),
    });
  }

  if (metrics.length === 0) return null;

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 bg-muted/30 rounded-md border text-[11px] tabular-nums">
      {isStreaming && (
        <span className="flex items-center gap-1 text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          流式中
        </span>
      )}
      {metrics.map((m, i) => (
        <span key={i} className="flex items-center gap-1 text-muted-foreground">
          {m.icon}
          <span className="text-foreground/70">{m.label}</span>
          <span className="font-medium text-foreground">{m.value}</span>
        </span>
      ))}
    </div>
  );
}
