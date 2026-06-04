import {
  Container,
  Cpu,
  HardDrive,
  Clock,
  Globe,
  WifiOff,
  Shield,
  Network,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SandboxCardProps {
  image?: string | null;
  cpuLimit?: number | null;
  memoryMb?: number | null;
  timeoutSeconds?: number | null;
  network?: string | null;
  requiresSandbox?: boolean;
}

export function SandboxCard({
  image,
  cpuLimit,
  memoryMb,
  timeoutSeconds,
  network,
  requiresSandbox,
}: SandboxCardProps) {
  const cpu = cpuLimit ?? 0.5;
  const mem = memoryMb ?? 256;
  const timeout = timeoutSeconds ?? 60;
  const net = network ?? "none";
  const img = image ?? "python:3.12-slim";

  const netLabel: Record<string, string> = {
    none: "无网络",
    internal: "内网",
    whitelist: "白名单",
    full: "全网络",
  };
  const netColor: Record<string, string> = {
    none: "text-gray-400",
    internal: "text-blue-500",
    whitelist: "text-yellow-500",
    full: "text-red-500",
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Container className="w-4 h-4 text-blue-500" />
          沙箱环境
          {!requiresSandbox && (
            <span className="text-[10px] text-muted-foreground ml-auto">(未启用)</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Docker 镜像 */}
        <div className="flex items-center gap-2 text-xs">
          <Container className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-muted-foreground">镜像:</span>
          <code className="bg-muted px-1.5 py-0.5 rounded text-[11px] font-mono ml-auto">
            {img}
          </code>
        </div>

        {/* CPU 限制 */}
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs">
            <Cpu className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground">CPU 限制</span>
            <span className="ml-auto font-mono text-[11px]">{cpu} 核</span>
          </div>
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                cpu <= 0.5 ? "bg-green-400" : cpu <= 1 ? "bg-yellow-400" : "bg-red-400"
              )}
              style={{ width: `${Math.min(cpu * 50, 100)}%` }}
            />
          </div>
        </div>

        {/* 内存限制 */}
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs">
            <HardDrive className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground">内存限制</span>
            <span className="ml-auto font-mono text-[11px]">{mem} MB</span>
          </div>
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                mem <= 128 ? "bg-green-400" : mem <= 512 ? "bg-yellow-400" : "bg-red-400"
              )}
              style={{ width: `${Math.min(mem / 10, 100)}%` }}
            />
          </div>
        </div>

        {/* 超时时间 */}
        <div className="flex items-center gap-2 text-xs">
          <Clock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-muted-foreground">执行超时</span>
          <span className="ml-auto font-mono text-[11px]">{timeout}s</span>
        </div>

        {/* 网络模式 */}
        <div className="flex items-center gap-2 text-xs">
          {net === "none" ? (
            <WifiOff className="w-3.5 h-3.5 shrink-0" />
          ) : (
            <Globe className={cn("w-3.5 h-3.5 shrink-0", netColor[net])} />
          )}
          <span className="text-muted-foreground">网络</span>
          <span
            className={cn(
              "ml-auto text-[11px] font-medium px-1.5 py-0.5 rounded",
              net === "none" && "bg-gray-100 text-gray-500",
              net === "internal" && "bg-blue-50 text-blue-600",
              net === "whitelist" && "bg-yellow-50 text-yellow-600",
              net === "full" && "bg-red-50 text-red-600"
            )}
          >
            {netLabel[net] ?? net}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
