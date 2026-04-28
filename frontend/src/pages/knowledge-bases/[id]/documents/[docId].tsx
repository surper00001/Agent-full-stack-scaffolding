import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useKBStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { viewDocument } from "@/api/knowledge-base";
import { KBBlockRenderer } from "@/components/kb/kb-block-renderer";
import { PdfPageViewer } from "@/components/kb/pdf-page-viewer";
import { cn } from "@/lib/utils";
import type { KBDocumentView } from "@/types";
import {
  ArrowLeft, Download, ChevronLeft, ChevronRight, FileText, LayoutGrid,
} from "lucide-react";

type ViewMode = "pdf" | "structured" | "split";

export default function DocumentViewerPage() {
  const { id: kbId, docId } = useParams<{ id: string; docId: string }>();
  const { fetchKB } = useKBStore();
  const [docView, setDocView] = useState<KBDocumentView | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("split");
  const [highlightIndex, setHighlightIndex] = useState<number | null>(null);

  const isPdf = docView?.file_type?.toLowerCase() === "pdf";

  useEffect(() => {
    if (!kbId || !docId) return;
    fetchKB(kbId);
    setLoading(true);
    viewDocument(kbId, docId)
      .then((res) => {
        setDocView(res.data);
        setLoading(false);
      })
      .catch((err) => {
        setError((err as Error).message);
        setLoading(false);
      });
  }, [kbId, docId, fetchKB]);

  if (loading) return <LoadingSpinner size="lg" className="mt-12" />;
  if (error) return <EmptyState title="加载失败" description={error} />;
  if (!docView || !kbId || !docId) return <EmptyState title="文档不存在" />;

  const totalPages = docView.total_pages;
  const currentPageData = docView.pages.find((p) => p.page_number === currentPage);
  const pageBlocks = currentPageData?.text_blocks ?? [];
  const pageHasContent = currentPageData?.has_content ?? pageBlocks.length > 0;

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
            <h1 className="text-lg font-bold">{docView.filename}</h1>
            {docView.doc_category_label && (
              <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                {docView.doc_category_label}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {totalPages} 页 · 共 {docView.pages.reduce((s, p) => s + p.text_blocks.length, 0)} 个内容块
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
              {pageHasContent ? (
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
                        type: block.type,
                        content: block.content,
                        table_html: block.table_html,
                        image_url: block.image_url,
                        ocr_status: block.ocr_status,
                        ocr_error: block.ocr_error,
                        image_caption: block.image_caption,
                        image_description: block.image_description,
                        section_title: block.section_title,
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
        <div className="flex items-center justify-center gap-2">
          {Array.from({ length: Math.min(totalPages, 20) }, (_, i) => i + 1).map((p) => {
            const pageEntry = docView.pages.find((pg) => pg.page_number === p);
            const empty = !(pageEntry?.has_content ?? (pageEntry?.text_blocks?.length ?? 0) > 0);
            return (
            <button
              key={p}
              onClick={() => { setCurrentPage(p); setHighlightIndex(null); }}
              title={empty ? "本页无结构化内容" : undefined}
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
