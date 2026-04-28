import { useEffect, useMemo, useState } from "react";
import { fetchPagePreviewBlob } from "@/api/knowledge-base";
import type { KBPageBlock } from "@/types";
import { cn } from "@/lib/utils";
import { LoadingSpinner } from "@/components/common/loading-spinner";

interface PdfPageViewerProps {
  kbId: string;
  docId: string;
  pageNumber: number;
  blocks: KBPageBlock[];
  /** 外部点击结构化块时传入，用于高亮对应 bbox */
  highlightIndex?: number | null;
  className?: string;
}

const BBOX_COLORS: Record<string, string> = {
  table: "stroke-amber-500 fill-amber-500/10",
  image: "stroke-blue-500 fill-blue-500/10",
  text: "stroke-emerald-500/60 fill-emerald-500/5",
};

export function PdfPageViewer({
  kbId,
  docId,
  pageNumber,
  blocks,
  highlightIndex = null,
  className,
}: PdfPageViewerProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const { blob, pageWidth, pageHeight } = await fetchPagePreviewBlob(
          kbId,
          docId,
          pageNumber,
        );
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
        setPageSize({ width: pageWidth, height: pageHeight });
      } catch (err) {
        if (!revoked) setError((err as Error).message || "页面预览加载失败");
      } finally {
        if (!revoked) setLoading(false);
      }
    };

    void load();

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [kbId, docId, pageNumber]);

  const overlayBlocks = useMemo(
    () =>
      blocks
        .map((block, idx) => ({ block, idx }))
        .filter(({ block }) => block.bbox && block.bbox.length === 4),
    [blocks],
  );

  if (loading) {
    return (
      <div className={cn("flex min-h-[320px] items-center justify-center rounded-md border bg-muted/10", className)}>
        <LoadingSpinner size="sm" />
      </div>
    );
  }

  if (error || !previewUrl) {
    return (
      <div className={cn("flex min-h-[200px] items-center justify-center rounded-md border bg-muted/10 p-4 text-sm text-muted-foreground", className)}>
        {error || "无法预览此页（仅 PDF 支持原页渲染）"}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "app-scrollbar relative max-h-[calc(100vh-14rem)] overflow-auto rounded-md border bg-muted/10",
        className,
      )}
    >
      <div className="relative inline-block min-w-full">
        <img
          src={previewUrl}
          alt={`第 ${pageNumber} 页`}
          className="block w-full h-auto"
          draggable={false}
        />
        {pageSize.width > 0 && pageSize.height > 0 && overlayBlocks.length > 0 && (
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox={`0 0 ${pageSize.width} ${pageSize.height}`}
            preserveAspectRatio="none"
          >
            {overlayBlocks.map(({ block, idx }) => {
              const [x0, y0, x1, y1] = block.bbox!;
              const isHighlight = highlightIndex === idx;
              const colorClass = BBOX_COLORS[block.type] || BBOX_COLORS.text;
              return (
                <rect
                  key={idx}
                  x={x0}
                  y={y0}
                  width={x1 - x0}
                  height={y1 - y0}
                  className={cn(
                    colorClass,
                    "stroke-2",
                    isHighlight && "animate-pulse stroke-[3]",
                  )}
                  rx={2}
                />
              );
            })}
          </svg>
        )}
      </div>
      <div className="flex flex-wrap gap-3 border-t bg-background/80 px-3 py-2 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm border-2 border-amber-500 bg-amber-500/20" />
          表格
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm border-2 border-blue-500 bg-blue-500/20" />
          图片
        </span>
      </div>
    </div>
  );
}
