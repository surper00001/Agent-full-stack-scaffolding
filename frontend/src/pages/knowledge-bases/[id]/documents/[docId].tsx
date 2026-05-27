import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useKBStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { viewDocument, viewDocumentPages } from "@/api/knowledge-base";
import { KBBlockRenderer } from "@/components/kb/kb-block-renderer";
import { PdfPageViewer } from "@/components/kb/pdf-page-viewer";
import { cn } from "@/lib/utils";
import type { KBPageContent } from "@/types";
import {
  ArrowLeft, Download, ChevronLeft, ChevronRight, FileText, LayoutGrid,
} from "lucide-react";

type ViewMode = "pdf" | "structured" | "split";

/** 页面元数据（轻量，导航用） */
interface PageMeta {
  page_number: number;
  has_content: boolean;
}

export default function DocumentViewerPage() {
  const { id: kbId, docId } = useParams<{ id: string; docId: string }>();
  const { fetchKB } = useKBStore();

  // ── 文档元数据 ──
  const [filename, setFilename] = useState("");
  const [fileType, setFileType] = useState("");
  const [totalPages, setTotalPages] = useState(0);
  const [pagesMeta, setPagesMeta] = useState<PageMeta[]>([]);
  const [docCategory, setDocCategory] = useState<string | undefined>();
  const [metaLoading, setMetaLoading] = useState(true);
  const [metaError, setMetaError] = useState<string | null>(null);

  // ── 按需页面缓存 ──
  const pageCache = useRef<Map<number, KBPageContent>>(new Map());
  const pendingRef = useRef<Set<number>>(new Set()); // 防止并发重复请求
  const [currentPage, setCurrentPage] = useState(1);
  const [pageLoading, setPageLoading] = useState(false); // 仅在缓存未命中时 true
  const [highlightIndex, setHighlightIndex] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("split");

  const isPdf = fileType?.toLowerCase() === "pdf";

  // ── 初始化：加载页面元数据（轻量） ──
  useEffect(() => {
    if (!kbId || !docId) return;
    fetchKB(kbId);
    setMetaLoading(true);
    viewDocumentPages(kbId, docId)
      .then((res) => {
        const d = res.data;
        setFilename(d.filename);
        setFileType(d.file_type);
        setTotalPages(d.total_pages);
        setPagesMeta(d.pages);
        setDocCategory(d.doc_category_label);
        setMetaLoading(false);
      })
      .catch((err) => {
        setMetaError((err as Error).message);
        setMetaLoading(false);
      });
  }, [kbId, docId, fetchKB]);

  // ── 按需加载指定页 ──
  const loadPage = useCallback(
    async (pageNum: number) => {
      if (!kbId || !docId) return;
      // 已缓存 → 直接返回
      if (pageCache.current.has(pageNum)) return;
      // 正在请求中 → 不重复发
      if (pendingRef.current.has(pageNum)) return;

      pendingRef.current.add(pageNum);
      try {
        const res = await viewDocument(kbId, docId, pageNum);
        const pageData = res.data.page ?? (res.data as unknown as { pages: KBPageContent[] }).pages?.[0];
        if (pageData) {
          pageCache.current.set(pageNum, pageData);
          // 触发重渲染
          setPageLoading((p) => !p); // toggle 强制刷新
        }
      } catch {
        // 静默失败，显示空页
      } finally {
        pendingRef.current.delete(pageNum);
      }
    },
    [kbId, docId],
  );

  // ── 翻页时加载当前页 + 预加载下一页 ──
  useEffect(() => {
    if (!kbId || !docId || totalPages === 0) return;
    const cached = pageCache.current.has(currentPage);
    if (!cached) {
      setPageLoading(true);
      loadPage(currentPage).finally(() => setPageLoading(false));
    }
    // 预加载下一页
    const next = currentPage + 1;
    if (next <= totalPages && !pageCache.current.has(next)) {
      loadPage(next);
    }
    // 预加载上一页
    const prev = currentPage - 1;
    if (prev >= 1 && !pageCache.current.has(prev)) {
      loadPage(prev);
    }
  }, [currentPage, totalPages, kbId, docId, loadPage]);

  // ── 渲染 ──
  if (metaLoading) return <LoadingSpinner size="lg" className="mt-12" />;
  if (metaError) return <EmptyState title="加载失败" description={metaError} />;
  if (!kbId || !docId) return <EmptyState title="文档不存在" />;

  const currentPageData = pageCache.current.get(currentPage);
  const pageBlocks = currentPageData?.text_blocks ?? [];
  const pageHasContent = currentPageData?.has_content ?? pageBlocks.length > 0;
  const isLoadingPage = pageLoading && !currentPageData;

  const showPdf = isPdf && (viewMode === "pdf" || viewMode === "split");
  const showStructured = viewMode === "structured" || viewMode === "split";
  const panelScrollClass =
    "app-scrollbar max-h-[calc(100vh-14rem)] overflow-y-auto overflow-x-auto";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          to={`/kb/${kbId}`}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold">{filename}</h1>
            {docCategory && (
              <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                {docCategory}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {totalPages} 页 · 共 {pagesMeta.filter((p) => p.has_content).length} 页有内容
          </p>
        </div>
        {isPdf && (
          <div className="flex rounded-md border p-0.5">
            {([
              { mode: "split" as ViewMode, icon: LayoutGrid, label: "对照" },
              { mode: "pdf" as ViewMode, icon: FileText, label: "原页" },
              { mode: "structured" as ViewMode, icon: FileText, label: "结构化" },
            ]).map(({ mode, label }) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  viewMode === mode
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        <a
          href={`/api/v1/knowledge-bases/${kbId}/documents/${docId}/download`}
          download
        >
          <Button variant="outline" size="sm">
            <Download className="mr-1 h-4 w-4" />下载源文件
          </Button>
        </a>
      </div>

      {/* Page Navigator */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button
            variant="outline" size="sm"
            disabled={currentPage <= 1}
            onClick={() => { setCurrentPage((p) => Math.max(1, p - 1)); setHighlightIndex(null); }}
          >
            <ChevronLeft className="h-4 w-4 mr-1" />上一页
          </Button>
          <span className="text-sm tabular-nums">
            {currentPage} / {totalPages}
          </span>
          <Button
            variant="outline" size="sm"
            disabled={currentPage >= totalPages}
            onClick={() => { setCurrentPage((p) => Math.min(totalPages, p + 1)); setHighlightIndex(null); }}
          >
            下一页<ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )}

      {/* Page Content */}
      <div className={`grid gap-4 ${showPdf && showStructured ? "lg:grid-cols-2" : "grid-cols-1"}`}>
        {showPdf && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">PDF 原页 · 第 {currentPage} 页</CardTitle>
            </CardHeader>
            <CardContent className={panelScrollClass}>
              <PdfPageViewer
                kbId={kbId}
                docId={docId}
                pageNumber={currentPage}
                blocks={pageBlocks}
                highlightIndex={highlightIndex}
              />
            </CardContent>
          </Card>
        )}

        {showStructured && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">结构化内容 · 第 {currentPage} 页</CardTitle>
            </CardHeader>
            <CardContent className={cn(panelScrollClass, "space-y-4")}>
              {isLoadingPage ? (
                <LoadingSpinner size="md" className="py-8" />
              ) : pageHasContent ? (
                pageBlocks.map((block, idx) => (
                  <div
                    key={idx}
                    role="button"
                    tabIndex={0}
                    onClick={() => setHighlightIndex(idx)}
                    onKeyDown={(e) => e.key === "Enter" && setHighlightIndex(idx)}
                    className={`rounded-md p-2 transition-colors cursor-pointer ${
                      highlightIndex === idx
                        ? "bg-primary/5 ring-1 ring-primary/30"
                        : "hover:bg-muted/30"
                    }`}
                  >
                    <KBBlockRenderer
                      block={{
                        type: block.type as "text" | "table" | "image" | "code" | "reference" | "formula",
                        content: block.content,
                        table_html: block.table_html,
                        image_url: block.image_url,
                        ocr_status: block.ocr_status,
                        ocr_error: block.ocr_error,
                        image_caption: block.image_caption,
                        image_description: block.image_description,
                        section_title: block.section_title,
                        image_width: block.image_width,
                        image_height: block.image_height,
                      }}
                      kbId={kbId}
                      docId={docId}
                    />
                  </div>
                ))
              ) : (
                <EmptyState
                  title="本页未提取到结构化内容"
                  description={
                    isPdf
                      ? "可能是扫描页或版式复杂。左侧可查看 PDF 原页；若需文字检索，请在后台开启 OCR（KB_OCR_ENABLED）后重新处理文档。"
                      : "该页没有识别到文字、表格或图片块。"
                  }
                />
              )}
            </CardContent>
          </Card>
        )}

        {!showPdf && !showStructured && (
          <EmptyState title="请选择查看模式" description="PDF 支持原页对照或结构化浏览" />
        )}
      </div>

      {/* Bottom page nav */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 flex-wrap">
          {Array.from({ length: Math.min(totalPages, 20) }, (_, i) => i + 1).map((p) => {
            const meta = pagesMeta.find((pg) => pg.page_number === p);
            const empty = !(meta?.has_content);
            return (
              <button
                key={p}
                onClick={() => { setCurrentPage(p); setHighlightIndex(null); }}
                title={empty ? "本页无结构化内容" : `第 ${p} 页`}
                className={`h-8 w-8 rounded text-xs font-medium transition-colors ${
                  p === currentPage
                    ? "bg-primary text-primary-foreground"
                    : empty
                      ? "border border-dashed border-muted-foreground/40 text-muted-foreground/60 hover:bg-muted"
                      : "hover:bg-muted text-muted-foreground"
                }`}
              >
                {p}
              </button>
            );
          })}
          {totalPages > 20 && <span className="text-xs text-muted-foreground">...</span>}
        </div>
      )}
    </div>
  );
}
