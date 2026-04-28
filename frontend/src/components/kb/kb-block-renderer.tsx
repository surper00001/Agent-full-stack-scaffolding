import { AuthenticatedImage } from "./authenticated-image";

/** 知识库内容块通用字段（文档查看 + 搜索结果共用） */
export interface KBBlockData {
  type: "text" | "table" | "image" | "code";
  content: string;
  table_html?: string | null;
  image_url?: string | null;
  ocr_status?: "success" | "empty" | "failed" | "disabled" | null;
  ocr_error?: string | null;
  image_caption?: string | null;
  image_description?: string | null;
  section_title?: string | null;
}

interface KBBlockRendererProps {
  block: KBBlockData;
  kbId?: string;
  docId?: string;
  compact?: boolean;
}

function getOcrLabel(status?: KBBlockData["ocr_status"]): string {
  switch (status) {
    case "success":
      return "图片 OCR 结果";
    case "failed":
      return "图片（OCR 失败）";
    case "empty":
      return "图片（未识别到文字）";
    case "disabled":
      return "图片（OCR 已关闭）";
    default:
      return "图片";
  }
}

function stripPlaceholder(content: string): string {
  const placeholders = ["[图片]", "[图片 OCR 失败]"];
  return placeholders.includes(content.trim()) ? "" : content;
}

/** 旧数据或误识别：单列/无表头的 HTML 按纯文本展示 */
function shouldRenderTableAsText(tableHtml: string): boolean {
  const thCount = (tableHtml.match(/<th\b/gi) || []).length;
  const tdCount = (tableHtml.match(/<td\b/gi) || []).length;
  if (thCount === 0 && tdCount <= 2) return true;
  const colMatch = tableHtml.match(/<tr[^>]*>[\s\S]*?<\/tr>/i);
  if (!colMatch) return false;
  const cells = (colMatch[0].match(/<t[dh]\b/gi) || []).length;
  return cells <= 1;
}

export function KBBlockRenderer({ block, kbId, docId, compact = false }: KBBlockRendererProps) {
  if (block.type === "table" && block.table_html) {
    if (shouldRenderTableAsText(block.table_html)) {
      const plain = block.content.replace(/^\[表格\]\s*/, "").trim() || block.content;
      return (
        <div className="text-sm leading-relaxed whitespace-pre-wrap">{plain}</div>
      );
    }
    return (
      <div className="space-y-1">
        {!compact && <p className="text-xs text-muted-foreground">表格</p>}
        <div
          className="kb-table-wrapper"
          dangerouslySetInnerHTML={{ __html: block.table_html }}
        />
      </div>
    );
  }

  if (block.type === "image") {
    const ocrLabel = getOcrLabel(block.ocr_status);
    const displayText = stripPlaceholder(block.content);
    const canShowImage = kbId && docId && block.image_url;

    return (
      <div className="space-y-2">
        {!compact && <p className="text-xs text-muted-foreground">{ocrLabel}</p>}
        {canShowImage && (
          <AuthenticatedImage
            kbId={kbId}
            docId={docId}
            imageUrl={block.image_url}
            alt={block.section_title || block.image_caption || "文档图片"}
            className={compact ? "max-h-48" : undefined}
          />
        )}
        {block.image_caption && (
          <p className="text-xs text-muted-foreground">说明：{block.image_caption}</p>
        )}
        {block.image_description && block.image_description !== displayText && (
          <p className="text-xs text-muted-foreground">描述：{block.image_description}</p>
        )}
        {(displayText || block.ocr_error || block.ocr_status === "empty") && (
          <div className="space-y-1 rounded-md border bg-muted/10 p-3 text-sm text-muted-foreground">
            {displayText && <p className="whitespace-pre-wrap">{displayText}</p>}
            {block.ocr_status === "empty" && !displayText && (
              <p className="text-xs">未识别到文字，后续可接入多模态识别</p>
            )}
            {block.ocr_error && (
              <p className="text-xs text-destructive/80">OCR 错误：{block.ocr_error}</p>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="text-sm leading-relaxed whitespace-pre-wrap">
      {block.section_title && (
        <h3 className={`mb-2 font-semibold text-foreground ${compact ? "text-sm" : "text-base"}`}>
          {block.section_title}
        </h3>
      )}
      {block.content}
    </div>
  );
}
