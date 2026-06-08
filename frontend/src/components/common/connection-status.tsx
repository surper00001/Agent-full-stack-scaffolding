import { Wifi, WifiOff, Loader2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ConnectionStatusProps {
  status: "idle" | "connected" | "reconnecting" | "disconnected" | "error";
  retryCount?: number;
  className?: string;
}

export function ConnectionStatus({ status, retryCount = 0, className }: ConnectionStatusProps) {
  if (status === "idle") return null;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium border",
        status === "connected" && "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-800",
        status === "reconnecting" && "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800",
        status === "error" && "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/30 dark:text-red-300 dark:border-red-800",
        status === "disconnected" && "bg-muted text-muted-foreground border-border",
        className,
      )}
    >
      {status === "connected" && <Wifi className="h-3 w-3" />}
      {status === "reconnecting" && <Loader2 className="h-3 w-3 animate-spin" />}
      {status === "error" && <AlertTriangle className="h-3 w-3" />}
      {status === "disconnected" && <WifiOff className="h-3 w-3" />}

      {status === "connected" && "已连接"}
      {status === "reconnecting" && `重连中 (${retryCount})`}
      {status === "error" && "连接失败"}
      {status === "disconnected" && "已断开"}
    </div>
  );
}
