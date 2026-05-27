import { Upload, Search, FileText, RefreshCw, XCircle, Trash2, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { UploadProgress } from "@/stores/knowledge-base-store";

const HardDriveIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M22 12H2M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" />
  </svg>
);

const STAGE_ICONS: Record<string, LucideIcon> = {
  uploading: Upload,
  uploaded: Upload,
  analyzing: Search,
  parsing: FileText,
  chunking: FileText,
  embedding: RefreshCw,
  indexing: HardDriveIcon as LucideIcon,
  ready: FileText,
  error: FileText,
};

const STAGE_ORDER = ["uploading", "uploaded", "analyzing", "parsing", "chunking", "embedding", "indexing", "ready"];

function formatETA(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
}

interface ProcessingProgressCardProps {
  progress: UploadProgress;
  onCancel?: () => void;
  onDelete?: () => void;
  onRetry?: () => void;
  onReprocess?: () => void;
}

export function ProcessingProgressCard({
  progress, onCancel, onDelete, onRetry, onReprocess,
}: ProcessingProgressCardProps) {
  const { stage, stageLabel, percentage, estimatedSeconds, errorMessage, filename } = progress;
  const isError = stage === "error";
  const isReady = stage === "ready";
  const isCancelled = stage === "cancelled";
  const isActive = !isError && !isReady && !isCancelled;
  const Icon = STAGE_ICONS[stage] || RefreshCw;

  const borderClass = isError
    ? "border-red-300 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20"
    : isReady
      ? "border-green-300 dark:border-green-800 bg-green-50/50 dark:bg-green-950/20"
      : isCancelled
        ? "border-yellow-300 dark:border-yellow-800 bg-yellow-50/50 dark:bg-yellow-950/20"
        : "border-blue-300 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/20";

  return (
    <Card className={`border-2 ${borderClass}`}>
      <CardContent className="py-4 space-y-3">
        <div className="flex items-center gap-3">
          <Icon
            className={`h-5 w-5 shrink-0 ${
              isError
                ? "text-red-500"
                : isCancelled
                  ? "text-yellow-500"
                  : isReady
                    ? "text-green-500"
                    : isActive
                      ? "text-blue-500 animate-pulse"
                      : "text-muted-foreground"
            }`}
          />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">
              {isReady ? "✓ " : isError ? "✗ " : isCancelled ? "⊘ " : ""}
              {filename}
            </p>
            <p
              className={`text-xs ${
                isError
                  ? "text-red-600 dark:text-red-400"
                  : isCancelled
                    ? "text-yellow-600 dark:text-yellow-400"
                    : isReady
                      ? "text-green-600 dark:text-green-400"
                      : "text-blue-600 dark:text-blue-400"
              }`}
            >
              {stageLabel}
            </p>
          </div>
          <span
            className={`text-sm font-mono font-bold tabular-nums shrink-0 ${
              isError ? "text-red-500" : isCancelled ? "text-yellow-500" : isReady ? "text-green-500" : "text-blue-500"
            }`}
          >
            {percentage.toFixed(0)}%
          </span>
        </div>

        <div className="relative h-2 bg-muted rounded-full overflow-hidden">
          <div
            className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ease-out ${
              isError ? "bg-red-500" : isCancelled ? "bg-yellow-500" : isReady ? "bg-green-500" : "bg-blue-500"
            }`}
            style={{ width: `${Math.min(percentage, 100)}%` }}
          />
        </div>

        <div className="flex items-center justify-between">
          {[
            { key: "parsing", label: "解析" },
            { key: "chunking", label: "分块" },
            { key: "embedding", label: "向量化" },
            { key: "indexing", label: "入库" },
          ].map((s) => {
            const currentIdx = STAGE_ORDER.indexOf(stage);
            const itemIdx = STAGE_ORDER.indexOf(s.key);
            let dotClass = "bg-muted-foreground/20";
            if (isError) dotClass = "bg-red-300";
            else if (isCancelled) dotClass = "bg-yellow-300";
            else if (isReady) dotClass = "bg-green-500";
            else if (itemIdx < currentIdx) dotClass = "bg-blue-500";
            else if (itemIdx === currentIdx) dotClass = "bg-blue-500 animate-pulse";

            return (
              <div key={s.key} className="flex items-center gap-1">
                <div className={`h-2.5 w-2.5 rounded-full ${dotClass}`} />
                <span
                  className={`text-[10px] ${
                    itemIdx <= currentIdx && !isCancelled ? "text-foreground" : "text-muted-foreground/40"
                  }`}
                >
                  {s.label}
                </span>
              </div>
            );
          })}
          {estimatedSeconds != null && isActive && (
            <span className="text-[10px] text-muted-foreground tabular-nums ml-auto">
              预计剩余 {formatETA(estimatedSeconds)}
            </span>
          )}
        </div>

        {errorMessage && (
          <p className="text-xs text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30 rounded p-2">
            {errorMessage}
          </p>
        )}

        {/* 活跃阶段：取消 + 删除按钮 */}
        {isActive && (
          <div className="flex gap-2">
            {onCancel && (
              <Button variant="outline" size="sm" className="flex-1" onClick={onCancel}>
                <XCircle className="mr-1 h-3.5 w-3.5" />
                取消
              </Button>
            )}
            {onDelete && (
              <Button variant="outline" size="sm" className="flex-1" onClick={onDelete}>
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                删除
              </Button>
            )}
          </div>
        )}

        {/* 已取消：重试 + 删除按钮 */}
        {isCancelled && (
          <div className="flex gap-2">
            {onRetry && (
              <Button variant="outline" size="sm" className="flex-1" onClick={onRetry}>
                <RefreshCw className="mr-1 h-3.5 w-3.5" />
                重试
              </Button>
            )}
            {onDelete && (
              <Button variant="outline" size="sm" className="flex-1" onClick={onDelete}>
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                删除
              </Button>
            )}
          </div>
        )}

        {/* 失败：重试 + 删除按钮（替代原来的只看 reprocess） */}
        {isError && (
          <div className="flex gap-2">
            {(onRetry || onReprocess) && (
              <Button variant="outline" size="sm" className="flex-1" onClick={onRetry || onReprocess}>
                <RefreshCw className="mr-1 h-3.5 w-3.5" />
                重新处理
              </Button>
            )}
            {onDelete && (
              <Button variant="outline" size="sm" className="flex-1" onClick={onDelete}>
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                删除
              </Button>
            )}
          </div>
        )}

        {progress.parsedPages != null && progress.totalPages != null && progress.totalPages > 0 && isActive && (
          <p className="text-[10px] text-muted-foreground">
            已解析 {progress.parsedPages}/{progress.totalPages} 页
            {progress.embeddedChunks != null && progress.totalChunks != null && (
              <> · 已向量化 {progress.embeddedChunks}/{progress.totalChunks} 块</>
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
