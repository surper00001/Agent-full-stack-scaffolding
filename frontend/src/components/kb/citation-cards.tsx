/**
 * 知识库引用卡片 — 展示 Agent 检索结果，图片块支持内联预览与灯箱放大。
 */
import { useState, useCallback, useEffect } from "react";
import { BookOpen, FileText, Image as ImageIcon, X, ZoomIn } from "lucide-react";

export interface KBCitation {
  chunk_id?: string;
  content: string;
  source: string;
  page: number;
  score: number;
  section_title?: string;
  chunk_type?: string;
  document_id?: string;
  image_url?: string;
  image_description?: string;
  image_caption?: string;
  ocr_status?: string;
}

interface CitationCardsProps {
  citations: KBCitation[];
}

/** 从 /api/v1/knowledge-bases/{kbId}/documents/{docId}/... 格式中解析 */
function parseImageUrl(imageUrl: string): {
  kbId: string;
  docId: string;
  mode: "image" | "download";
  name?: string;
} | null {
  const m = imageUrl.match(
    /\/knowledge-bases\/([^/]+)\/documents\/([^/]+)(?:\/images\/([^/?#]+)|\/download)/
  );
  if (!m) return null;
  const [, kbId, docId, name] = m;
  return {
    kbId,
    docId,
    mode: name ? "image" : "download",
    name,
  };
}

/** 图片灯箱 — 点击缩略图后在遮罩层中全屏预览 */
function ImageLightbox({
  imageUrl,
  kbId,
  docId,
  caption,
  description,
  onClose,
}: {
  imageUrl: string;
  kbId: string;
  docId: string;
  caption?: string;
  description?: string;
  onClose: () => void;
}) {
  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
    };
  }, [onKeyDown]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <button
        type="button"
        className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white/80 hover:bg-white/20 hover:text-white"
        onClick={onClose}
      >
        <X className="h-5 w-5" />
      </button>

      <div
        className="flex max-h-[90vh] max-w-[90vw] flex-col gap-3"
        onClick={(e) => e.stopPropagation()}
      >
        <KbImage
          imageUrl={imageUrl}
          kbId={kbId}
          docId={docId}
          className="max-h-[75vh] max-w-[85vw] rounded-lg object-contain"
        />
        {caption && (
          <p className="text-center text-xs font-medium text-white/90">{caption}</p>
        )}
        {description && (
          <p className="text-center text-xs text-white/70">{description}</p>
        )}
      </div>
    </div>
  );
}

/** 轻量知识库图片渲染 — 复用 AuthenticatedImage 的 blob 加载逻辑 */
function KbImage({
  imageUrl,
  kbId,
  docId,
  alt,
  className,
}: {
  imageUrl?: string | null;
  kbId: string;
  docId: string;
  alt?: string;
  className?: string;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!imageUrl) {
      setLoading(false);
      return;
    }

    let revoked = false;
    let objectUrl: string | null = null;

    const load = async () => {
      setLoading(true);
      setError(false);
      try {
        const { fetchDocumentDownloadBlob, fetchDocumentImageBlob } =
          await import("@/api/knowledge-base");
        const parsed = parseImageUrl(imageUrl);
        if (!parsed) {
          setError(true);
          return;
        }
        const blob =
          parsed.mode === "download"
            ? await fetchDocumentDownloadBlob(parsed.kbId, parsed.docId)
            : await fetchDocumentImageBlob(parsed.kbId, parsed.docId, parsed.name || "");
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch {
        if (!revoked) setError(true);
      } finally {
        if (!revoked) setLoading(false);
      }
    };

    void load();

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageUrl, kbId, docId]);

  if (!imageUrl) return null;
  if (loading) {
    return (
      <div className="flex h-24 w-full items-center justify-center rounded-md border bg-muted/20 text-xs text-muted-foreground">
        加载图片…
      </div>
    );
  }
  if (error || !blobUrl) {
    return (
      <div className="flex h-24 w-full flex-col items-center justify-center gap-1 rounded-md border bg-muted/20 text-xs text-muted-foreground">
        <ImageIcon className="h-5 w-5" />
        <span>图片加载失败</span>
      </div>
    );
  }
  return (
    <img
      src={blobUrl}
      alt={alt || "知识库图片"}
      className={className || "max-h-96 max-w-full rounded-md border bg-muted/20 object-contain"}
    />
  );
}

export function CitationCards({ citations }: CitationCardsProps) {
  const [expanded, setExpanded] = useState(false);
  const [lightbox, setLightbox] = useState<{
    imageUrl: string;
    kbId: string;
    docId: string;
    caption?: string;
    description?: string;
  } | null>(null);
  const displayCitations = expanded ? citations : citations.slice(0, 3);

  if (citations.length === 0) return null;

  return (
    <>
      <div className="px-4 pb-2">
        <div className="max-w-[75%] ml-11 space-y-2">
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
              <BookOpen className="h-3.5 w-3.5" />
              引用来源 ({citations.length})
            </div>
            {citations.length > 3 && (
              <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="text-[10px] text-primary hover:underline"
              >
                {expanded ? "收起" : `展开全部 ${citations.length} 条`}
              </button>
            )}
          </div>

          <div className="space-y-1.5">
            {displayCitations.map((cite, i) =>
              cite.image_url ? (
                <ImageCitationCard
                  key={cite.chunk_id || i}
                  cite={cite}
                  index={i}
                  onPreview={(url, kbId, docId, caption, desc) =>
                    setLightbox({ imageUrl: url, kbId, docId, caption, description: desc })
                  }
                />
              ) : (
                <TextCitationCard key={cite.chunk_id || i} cite={cite} index={i} />
              ),
            )}
          </div>
        </div>
      </div>

      {lightbox && (
        <ImageLightbox
          imageUrl={lightbox.imageUrl}
          kbId={lightbox.kbId}
          docId={lightbox.docId}
          caption={lightbox.caption}
          description={lightbox.description}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}

function ImageCitationCard({
  cite,
  index,
  onPreview,
}: {
  cite: KBCitation;
  index: number;
  onPreview: (
    url: string,
    kbId: string,
    docId: string,
    caption?: string,
    desc?: string,
  ) => void;
}) {
  const parsed = cite.image_url ? parseImageUrl(cite.image_url) : null;

  return (
    <div
      className="rounded-lg border bg-background/60 p-2.5 text-xs hover:border-primary/30 transition-colors cursor-pointer"
      onClick={() => {
        if (parsed) {
          onPreview(
            cite.image_url!,
            parsed.kbId,
            parsed.docId,
            cite.image_caption || cite.section_title,
            cite.image_description || cite.content,
          );
        }
      }}
    >
      {/* 缩略图 */}
      <div className="relative mb-2 overflow-hidden rounded-md border bg-muted/30">
        {parsed && (
          <KbImage
            imageUrl={cite.image_url}
            kbId={parsed.kbId}
            docId={parsed.docId}
            alt={cite.image_caption || cite.section_title || "知识库图片"}
            className="w-full max-h-40 object-contain"
          />
        )}
        <div className="absolute right-1.5 top-1.5 flex items-center gap-1 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white/80">
          <ZoomIn className="h-3 w-3" />
          预览
        </div>
      </div>

      {/* 来源信息 */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-violet-100 dark:bg-violet-900/30 text-[10px] font-bold text-violet-700 dark:text-violet-400">
          {index + 1}
        </div>
        <ImageIcon className="h-3 w-3 text-violet-500 shrink-0" />
        <span className="font-medium truncate">{cite.source}</span>
        <span className="text-[10px] text-muted-foreground shrink-0">
          第{cite.page}页
        </span>
        <span className="text-[10px] shrink-0 rounded-full bg-green-100 dark:bg-green-900/30 px-1.5 py-0.5 text-green-700 dark:text-green-400 font-mono">
          {Math.round(cite.score * 100)}%
        </span>
      </div>

      {/* 描述信息 */}
      {(cite.image_description || cite.image_caption) && (
        <div className="mt-2 space-y-0.5">
          {cite.image_description && (
            <p className="text-[11px] leading-relaxed text-muted-foreground line-clamp-2">
              {cite.image_description}
            </p>
          )}
          {cite.image_caption && (
            <p className="text-[10px] text-muted-foreground/60">{cite.image_caption}</p>
          )}
        </div>
      )}
    </div>
  );
}

function TextCitationCard({ cite, index }: { cite: KBCitation; index: number }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border bg-background/60 p-2.5 text-xs hover:border-primary/30 transition-colors">
      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-blue-100 dark:bg-blue-900/30 text-[10px] font-bold text-blue-700 dark:text-blue-400">
        {index + 1}
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
          <span className="font-medium truncate">{cite.source}</span>
          <span className="text-[10px] text-muted-foreground shrink-0">
            第{cite.page}页
          </span>
          <span className="text-[10px] shrink-0 rounded-full bg-green-100 dark:bg-green-900/30 px-1.5 py-0.5 text-green-700 dark:text-green-400 font-mono">
            {Math.round(cite.score * 100)}%
          </span>
        </div>
        {cite.section_title && (
          <p className="text-[10px] text-muted-foreground/70">{cite.section_title}</p>
        )}
        <p className="text-[11px] leading-relaxed text-muted-foreground line-clamp-3">
          {cite.content}
        </p>
      </div>
    </div>
  );
}

// ---- Parsers ----

/** 从 metadata 或 rag_context 解析引用列表 */
export function parseCitationsFromArray(raw: unknown): KBCitation[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((r): r is Record<string, unknown> => !!r && typeof r === "object")
    .map((r) => ({
      chunk_id: typeof r.chunk_id === "string" ? r.chunk_id : undefined,
      content: typeof r.content === "string" ? r.content : "",
      source: typeof r.source === "string" ? r.source : "未知",
      page: typeof r.page === "number" ? r.page : 1,
      score: typeof r.score === "number" ? r.score : 0,
      section_title: typeof r.section_title === "string" ? r.section_title : undefined,
      document_id: typeof r.document_id === "string" ? r.document_id : undefined,
      chunk_type: typeof r.chunk_type === "string" ? r.chunk_type : undefined,
      image_url: typeof r.image_url === "string" ? r.image_url : undefined,
      image_description:
        typeof r.image_description === "string" ? r.image_description : undefined,
      image_caption: typeof r.image_caption === "string" ? r.image_caption : undefined,
      ocr_status: typeof r.ocr_status === "string" ? r.ocr_status : undefined,
    }));
}

/** 从 tool_result JSON 解析引用列表 */
export function parseKBCitations(toolResult: string): KBCitation[] {
  try {
    const parsed = JSON.parse(toolResult) as {
      results?: Array<{
        content?: string;
        source?: string;
        document_filename?: string;
        page?: number;
        page_start?: number;
        score?: number;
        section_title?: string;
        chunk_id?: string;
        chunk_type?: string;
        document_id?: string;
        image_url?: string;
        image_description?: string;
        image_caption?: string;
        ocr_status?: string;
      }>;
    };
    if (!parsed.results?.length) return [];
    return parsed.results.map((r) => ({
      chunk_id: r.chunk_id,
      content: r.content || "",
      source: r.source || r.document_filename || "未知",
      page: r.page ?? r.page_start ?? 1,
      score: r.score ?? 0,
      section_title: r.section_title,
      chunk_type: r.chunk_type,
      document_id: r.document_id,
      image_url: r.image_url,
      image_description: r.image_description,
      image_caption: r.image_caption,
      ocr_status: r.ocr_status,
    }));
  } catch {
    return [];
  }
}
