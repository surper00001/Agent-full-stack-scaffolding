import { Brain, Wrench, MessageSquare, Check, Loader2, AlertCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TimelineEntry } from "@/types";

interface AgentTimelineProps {
  entries: TimelineEntry[];
  isStreaming?: boolean;
}

export function AgentTimeline({ entries, isStreaming }: AgentTimelineProps) {
  if (entries.length === 0) return null;

  return (
    <div className="relative pl-6 my-3 space-y-0">
      {/* Vertical line */}
      <div className="absolute left-[11px] top-2 bottom-2 w-px bg-border" />

      {entries.map((entry, _idx) => (
        <div key={entry.id} className="relative pb-3 last:pb-0">
          {/* Node dot */}
          <div
            className={cn(
              "absolute -left-[17px] top-1.5 h-4 w-4 rounded-full border-2 border-background flex items-center justify-center",
              entry.type === "thinking" && "bg-amber-500",
              entry.type === "tool_call" && entry.status === "running" && "bg-blue-400 animate-pulse",
              entry.type === "tool_call" && entry.status === "completed" && "bg-emerald-500",
              entry.type === "tool_call" && entry.status === "error" && "bg-red-500",
              entry.type === "tool_result" && "bg-violet-500",
              entry.type === "text" && "bg-primary",
            )}
          >
            {entry.type === "thinking" && <Brain className="h-2.5 w-2.5 text-white" />}
            {entry.type === "tool_call" && entry.status === "running" && <Loader2 className="h-2.5 w-2.5 text-white animate-spin" />}
            {entry.type === "tool_call" && entry.status === "completed" && <Check className="h-2.5 w-2.5 text-white" />}
            {entry.type === "tool_call" && entry.status === "error" && <AlertCircle className="h-2.5 w-2.5 text-white" />}
            {entry.type === "tool_result" && <Wrench className="h-2.5 w-2.5 text-white" />}
            {entry.type === "text" && <MessageSquare className="h-2.5 w-2.5 text-white" />}
          </div>

          {/* Content card */}
          <div
            className={cn(
              "rounded-md border px-2.5 py-1.5 text-xs",
              entry.type === "thinking" && "bg-amber-50/50 border-amber-200 dark:bg-amber-950/20 dark:border-amber-800",
              entry.type === "tool_call" && "bg-blue-50/50 border-blue-200 dark:bg-blue-950/20 dark:border-blue-800",
              entry.type === "tool_result" && "bg-violet-50/50 border-violet-200 dark:bg-violet-950/20 dark:border-violet-800",
              entry.type === "text" && "bg-muted/30 border-border",
            )}
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className="font-medium text-[11px]">
                {entry.type === "thinking" && "💭 思考"}
                {entry.type === "tool_call" && `🔧 ${entry.toolName || "工具调用"}`}
                {entry.type === "tool_result" && `📋 ${entry.toolName || "工具结果"}`}
                {entry.type === "text" && "📝 回复"}
              </span>
              <span className="text-[10px] text-muted-foreground ml-auto flex items-center gap-0.5 tabular-nums">
                <Clock className="h-2.5 w-2.5" />
                {(entry.elapsed_ms / 1000).toFixed(1)}s
                {entry.duration_ms != null && (
                  <span className="text-[10px]"> (耗时 {(entry.duration_ms / 1000).toFixed(1)}s)</span>
                )}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-3">
              {entry.content}
            </p>
          </div>
        </div>
      ))}

      {/* Streaming indicator */}
      {isStreaming && (
        <div className="relative pb-1">
          <div className="absolute -left-[17px] top-1.5 h-4 w-4 rounded-full border-2 border-background bg-muted-foreground/30 animate-pulse flex items-center justify-center">
            <Loader2 className="h-2.5 w-2.5 text-white animate-spin" />
          </div>
          <div className="rounded-md border border-dashed px-2.5 py-1 text-[10px] text-muted-foreground">
            执行中...
          </div>
        </div>
      )}
    </div>
  );
}
