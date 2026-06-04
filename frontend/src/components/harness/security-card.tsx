import { Shield, ShieldAlert, ShieldCheck, ShieldOff, AlertTriangle, Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const LEVEL_CONFIG: Record<
  string,
  { label: string; icon: typeof Shield; barColor: string; bgColor: string; textColor: string }
> = {
  low: {
    label: "低风险",
    icon: ShieldCheck,
    barColor: "bg-green-400",
    bgColor: "bg-green-50 border-green-200",
    textColor: "text-green-700",
  },
  medium: {
    label: "中风险",
    icon: Shield,
    barColor: "bg-yellow-400",
    bgColor: "bg-yellow-50 border-yellow-200",
    textColor: "text-yellow-700",
  },
  high: {
    label: "高风险",
    icon: ShieldAlert,
    barColor: "bg-orange-400",
    bgColor: "bg-orange-50 border-orange-200",
    textColor: "text-orange-700",
  },
  critical: {
    label: "关键",
    icon: ShieldOff,
    barColor: "bg-red-500",
    bgColor: "bg-red-50 border-red-200",
    textColor: "text-red-700",
  },
};

interface SecurityFinding {
  severity: "info" | "warning" | "error" | "critical";
  line: number;
  message: string;
  rule: string;
}

interface SecurityCardProps {
  securityLevel: string;
  requiresApproval?: boolean;
  scanResult?: string | null; // JSON string of SecurityScanData
  allowedImports?: string | null; // JSON array
  isReadOnly?: boolean;
}

function parseScanResult(raw: string | null | undefined): {
  passed: boolean;
  score: number;
  findings: SecurityFinding[];
} | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return {
      passed: parsed.passed ?? true,
      score: parsed.score ?? 100,
      findings: parsed.findings ?? [],
    };
  } catch {
    return null;
  }
}

function parseAllowedImports(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export function SecurityCard({
  securityLevel,
  requiresApproval,
  scanResult,
  allowedImports,
  isReadOnly,
}: SecurityCardProps) {
  const config = LEVEL_CONFIG[securityLevel] ?? LEVEL_CONFIG.low;
  const LevelIcon = config.icon;
  const scan = parseScanResult(scanResult);
  const imports = parseAllowedImports(allowedImports);

  const errorCount = scan?.findings.filter((f) => f.severity === "error" || f.severity === "critical").length ?? 0;
  const warningCount = scan?.findings.filter((f) => f.severity === "warning").length ?? 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Shield className="w-4 h-4 text-indigo-500" />
          安全护栏
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 安全级别 */}
        <div className={cn("p-3 rounded-lg border", config.bgColor)}>
          <div className="flex items-center gap-2">
            <LevelIcon className={cn("w-5 h-5", config.textColor)} />
            <div>
              <div className={cn("text-sm font-semibold", config.textColor)}>
                {config.label}
              </div>
              <div className="text-[11px] text-muted-foreground">
                安全级别: {securityLevel}
              </div>
            </div>
          </div>
        </div>

        {/* 安全评分条 */}
        {scan && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">安全扫描</span>
              <span className={cn("font-mono font-semibold", scan.passed ? "text-green-600" : "text-red-600")}>
                {scan.score}/100
              </span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  scan.score >= 90 ? "bg-green-400" : scan.score >= 70 ? "bg-yellow-400" : "bg-red-400"
                )}
                style={{ width: `${scan.score}%` }}
              />
            </div>
            {/* 发现统计 */}
            {(errorCount > 0 || warningCount > 0) && (
              <div className="flex gap-3 mt-1 text-[10px]">
                {errorCount > 0 && (
                  <span className="flex items-center gap-1 text-red-600">
                    <AlertTriangle className="w-3 h-3" />
                    {errorCount} 错误
                  </span>
                )}
                {warningCount > 0 && (
                  <span className="flex items-center gap-1 text-yellow-600">
                    <AlertTriangle className="w-3 h-3" />
                    {warningCount} 警告
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {/* 需要审批 */}
        {requiresApproval && (
          <div className="flex items-center gap-2 text-xs text-yellow-600 bg-yellow-50 px-2 py-1.5 rounded">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            此 Skill 执行前需要管理员审批
          </div>
        )}

        {/* 只读标识 */}
        {isReadOnly && (
          <div className="flex items-center gap-2 text-xs text-blue-600 bg-blue-50 px-2 py-1.5 rounded">
            <Check className="w-3.5 h-3.5 shrink-0" />
            只读 Skill — 不会修改任何文件
          </div>
        )}

        {/* 允许的模块 */}
        {imports.length > 0 && (
          <div>
            <div className="text-[10px] text-muted-foreground mb-1.5 font-medium">允许的模块</div>
            <div className="flex flex-wrap gap-1">
              {imports.map((mod) => (
                <code
                  key={mod}
                  className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-mono text-muted-foreground"
                >
                  {mod}
                </code>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
