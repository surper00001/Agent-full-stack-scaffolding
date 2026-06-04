import { useMemo } from "react";
import {
  CheckCircle2,
  Circle,
  AlertCircle,
  Play,
  ArrowRight,
  RotateCcw,
  Archive,
  ShieldAlert,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SkillDetail, SkillStatus } from "./types";

// 状态机定义：每个状态的可视化配置
const STATE_DEFS: Record<
  string,
  { label: string; icon: typeof Circle; color: string; description: string }
> = {
  draft: {
    label: "草稿",
    icon: Circle,
    color: "border-gray-400 text-gray-500 bg-gray-50",
    description: "Skill 正在编辑中，尚未就绪",
  },
  testing: {
    label: "测试中",
    icon: Play,
    color: "border-blue-400 text-blue-600 bg-blue-50",
    description: "在沙箱中验证功能",
  },
  pending_review: {
    label: "待审核",
    icon: Clock,
    color: "border-yellow-400 text-yellow-600 bg-yellow-50",
    description: "等待管理员安全审核",
  },
  approved: {
    label: "已审核",
    icon: CheckCircle2,
    color: "border-green-400 text-green-600 bg-green-50",
    description: "审核通过，可发布",
  },
  rejected: {
    label: "已拒绝",
    icon: AlertCircle,
    color: "border-red-400 text-red-600 bg-red-50",
    description: "审核未通过，需修改",
  },
  published: {
    label: "已发布",
    icon: CheckCircle2,
    color: "border-indigo-400 text-indigo-600 bg-indigo-50",
    description: "已发布，可安装使用",
  },
  active: {
    label: "已激活",
    icon: CheckCircle2,
    color: "border-emerald-400 text-emerald-600 bg-emerald-50",
    description: "正在运行，AI 可调用",
  },
  deprecated: {
    label: "已弃用",
    icon: Archive,
    color: "border-orange-400 text-orange-600 bg-orange-50",
    description: "已弃用，建议迁移",
  },
  archived: {
    label: "已归档",
    icon: Archive,
    color: "border-gray-300 text-gray-400 bg-gray-100",
    description: "已归档，不可使用",
  },
};

// 状态流转管道顺序
const PIPELINE_ORDER: string[] = [
  "draft",
  "testing",
  "pending_review",
  "approved",
  "published",
  "active",
];

// 每个状态允许的操作（按钮）
function getAllowedActions(
  currentStatus: string
): { target: string; label: string; variant: "default" | "outline" | "destructive" }[] {
  switch (currentStatus) {
    case "draft":
      return [
        { target: "testing", label: "提交测试", variant: "default" },
        { target: "pending_review", label: "提交审核", variant: "outline" },
      ];
    case "testing":
      return [
        { target: "pending_review", label: "提交审核", variant: "default" },
        { target: "draft", label: "退回编辑", variant: "outline" },
      ];
    case "pending_review":
      return [
        { target: "approved", label: "审核通过", variant: "default" },
        { target: "rejected", label: "审核拒绝", variant: "destructive" },
      ];
    case "rejected":
      return [{ target: "draft", label: "重新编辑", variant: "default" }];
    case "approved":
      return [{ target: "published", label: "发布上线", variant: "default" }];
    case "published":
      return [
        { target: "active", label: "激活使用", variant: "default" },
        { target: "deprecated", label: "弃用", variant: "outline" },
      ];
    case "active":
      return [
        { target: "deprecated", label: "弃用", variant: "outline" },
        { target: "published", label: "停用", variant: "outline" },
      ];
    case "deprecated":
      return [
        { target: "archived", label: "归档", variant: "outline" },
        { target: "active", label: "重新激活", variant: "default" },
      ];
    case "archived":
      return [{ target: "draft", label: "恢复为草稿", variant: "outline" }];
    default:
      return [];
  }
}

// ── StatePipeline 组件 ──

interface StatePipelineProps {
  currentStatus: string;
  onTransition: (targetStatus: string) => void;
  disabled?: boolean;
}

export function StatePipeline({
  currentStatus,
  onTransition,
  disabled,
}: StatePipelineProps) {
  const currentIdx = PIPELINE_ORDER.indexOf(currentStatus);
  const actions = useMemo(() => getAllowedActions(currentStatus), [currentStatus]);

  return (
    <div className="space-y-4">
      {/* 管道可视化 */}
      <div className="flex items-center gap-0 overflow-x-auto pb-2">
        {PIPELINE_ORDER.map((status, idx) => {
          const def = STATE_DEFS[status] ?? STATE_DEFS.draft;
          const isCompleted = idx < currentIdx;
          const isCurrent = status === currentStatus;
          const isFuture = idx > currentIdx;

          return (
            <div key={status} className="flex items-center shrink-0">
              {/* 状态节点 */}
              <div
                className={cn(
                  "flex flex-col items-center gap-1 px-2 py-2 rounded-lg border-2 min-w-[72px] transition-all",
                  isCurrent && "ring-2 ring-offset-1 scale-110 shadow-md",
                  isCompleted ? def.color : isCurrent ? def.color : "border-gray-200 text-gray-300 bg-gray-50/50"
                )}
                title={def.description}
              >
                {isCompleted ? (
                  <CheckCircle2 className="w-5 h-5 text-green-500" />
                ) : isCurrent ? (
                  <span className="relative flex h-5 w-5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-5 w-5 bg-emerald-500 items-center justify-center">
                      <Play className="w-3 h-3 text-white" />
                    </span>
                  </span>
                ) : (
                  <Circle className="w-5 h-5" />
                )}
                <span className={cn("text-[10px] font-medium", isFuture && "text-gray-300")}>
                  {def.label}
                </span>
              </div>

              {/* 连接线 */}
              {idx < PIPELINE_ORDER.length - 1 && (
                <div className="flex items-center -mx-1 z-0">
                  <div
                    className={cn(
                      "h-0.5 w-6",
                      idx < currentIdx
                        ? "bg-green-400"
                        : idx === currentIdx
                          ? "bg-gradient-to-r from-green-400 to-gray-200"
                          : "bg-gray-200"
                    )}
                  />
                  <ArrowRight
                    className={cn(
                      "w-3 h-3 shrink-0",
                      idx < currentIdx ? "text-green-400" : "text-gray-300"
                    )}
                  />
                </div>
              )}
            </div>
          );
        })}

        {/* 终止态：deprecated / archived */}
        {currentStatus === "deprecated" && (
          <>
            <ArrowRight className="w-3 h-3 text-orange-400 mx-1" />
            <div className="flex flex-col items-center gap-1 px-2 py-2 rounded-lg border-2 border-orange-400 text-orange-600 bg-orange-50 min-w-[72px] ring-2 ring-offset-1 scale-110 shadow-md">
              <Archive className="w-5 h-5" />
              <span className="text-[10px] font-medium">已弃用</span>
            </div>
          </>
        )}
        {currentStatus === "archived" && (
          <>
            <ArrowRight className="w-3 h-3 text-gray-400 mx-1" />
            <div className="flex flex-col items-center gap-1 px-2 py-2 rounded-lg border-2 border-gray-300 text-gray-400 bg-gray-100 min-w-[72px] ring-2 ring-offset-1 scale-110 shadow-md">
              <Archive className="w-5 h-5" />
              <span className="text-[10px] font-medium">已归档</span>
            </div>
          </>
        )}
      </div>

      {/* 当前状态说明 + 可用操作 */}
      <div className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">当前状态:</span>
          <span className={cn("text-sm font-semibold px-2 py-0.5 rounded-full", STATE_DEFS[currentStatus]?.color)}>
            {STATE_DEFS[currentStatus]?.label ?? currentStatus}
          </span>
          <span className="text-xs text-muted-foreground ml-2">
            {STATE_DEFS[currentStatus]?.description}
          </span>
        </div>
        <div className="flex gap-2">
          {actions.map((action) => (
            <Button
              key={action.target}
              size="sm"
              variant={action.variant}
              disabled={disabled}
              onClick={() => onTransition(action.target)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── 辅助：获取状态对应的中文标签 ──
export function getStatusLabel(status: string): string {
  return STATE_DEFS[status]?.label ?? status;
}

// ── 辅助：状态对应的颜色 class ──
export function getStatusColor(status: string): string {
  return STATE_DEFS[status]?.color ?? "border-gray-400 text-gray-500";
}

export type { SkillStatus };
