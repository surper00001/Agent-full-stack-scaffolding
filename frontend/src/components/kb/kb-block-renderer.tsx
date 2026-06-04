import { AuthenticatedImage } from "./authenticated-image";
import DOMPurify from "dompurify";

/** 知识库内容块通用字段（文档查看 + 搜索结果共用） */
export interface KBBlockData {
  type: "text" | "table" | "image" | "code" | "reference" | "formula";
  content: string;
  table_html?: string | null;
  table_caption?: string | null;
  image_url?: string | null;
  is_table_image?: boolean | null;
  ocr_status?: "success" | "empty" | "failed" | "disabled" | null;
  ocr_error?: string | null;
  image_caption?: string | null;
  image_description?: string | null;
  section_title?: string | null;
  image_width?: number | null;
  image_height?: number | null;
}

interface KBBlockRendererProps {
  block: KBBlockData;
  kbId?: string;
  docId?: string;
  compact?: boolean;
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

/** 解析表格 HTML，注入 kb-table class，统计行列数和合并单元格数 */
function prepareTableHtml(rawHtml: string): {
  html: string;
  rows: number;
  cols: number;
  mergedCells: number;
} {
  try {
    // eslint-disable-next-line no-undef -- browser built-in
    const parser = new DOMParser();
    const doc = parser.parseFromString(rawHtml, "text/html");
    const table = doc.querySelector("table");
    if (!table) return { html: rawHtml, rows: 0, cols: 0, mergedCells: 0 };

    table.classList.add("kb-table");

    // 统计行数
    const trs = table.querySelectorAll("tr");
    const rows = trs.length;

    // 首行列数（考虑 colspan）
    const firstRow = trs[0];
    let cols = 0;
    if (firstRow) {
      firstRow.querySelectorAll("th, td").forEach((cell) => {
        const cs = parseInt(cell.getAttribute("colspan") || "1", 10);
        cols += cs;
      });
    }

    // 统计合并单元格数
    let mergedCells = 0;
    table.querySelectorAll("td[colspan],th[colspan],td[rowspan],th[rowspan]").forEach((cell) => {
      const cs = parseInt(cell.getAttribute("colspan") || "1", 10);
      const rs = parseInt(cell.getAttribute("rowspan") || "1", 10);
      if (cs > 1 || rs > 1) mergedCells++;
    });

    return { html: table.outerHTML, rows, cols, mergedCells };
  } catch {
    return { html: rawHtml, rows: 0, cols: 0, mergedCells: 0 };
  }
}

export function KBBlockRenderer({ block, kbId, docId, compact = false }: KBBlockRendererProps) {
  if (block.type === "table" && block.table_html) {
    if (shouldRenderTableAsText(block.table_html)) {
      const plain = block.content.replace(/^\[表格.*?\]\s*/, "").trim() || block.content;
      return (
        <div className="text-sm leading-relaxed whitespace-pre-wrap">{plain}</div>
      );
    }
    const canShowImage = kbId && docId && block.image_url;
    const { html: processedHtml, rows, cols, mergedCells } = prepareTableHtml(block.table_html);
    return (
      <div className="space-y-2">
        {!compact && (
          <p className="text-xs text-muted-foreground">
            {block.is_table_image ? "表格（从图片提取）" : "表格"}
          </p>
        )}
        {block.table_caption && (
          <p className="text-xs font-medium text-foreground/80">{block.table_caption}</p>
        )}
        <div>
          {!compact && rows > 0 && (
            <div className="kb-table-info">
              <span>
                {rows} 行 × {cols} 列
                {mergedCells > 0 && (
                  <span className="text-muted-foreground/60"> · {mergedCells} 个合并单元格</span>
                )}
              </span>
            </div>
          )}
          <div
            className="kb-table-wrapper"
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(processedHtml) }}
          />
        </div>
        {canShowImage && (
          <details className="mt-2">
            <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
              查看原始图片
            </summary>
            <AuthenticatedImage
              kbId={kbId}
              docId={docId}
              imageUrl={block.image_url}
              alt={block.table_caption || "表格原图"}
              className="mt-2 max-h-64"
              imageWidth={block.image_width}
              imageHeight={block.image_height}
            />
          </details>
        )}
      </div>
    );
  }

  if (block.type === "reference") {
    return <ReferenceCard content={block.content} compact={compact} />;
  }

  if (block.type === "formula") {
    // 提取 LaTeX 公式内容
    const formulaText = block.content
      .replace(/^\$\$|\$\$$/g, "")
      .replace(/^\\\[|\\\]$/g, "")
      .trim();
    return (
      <div className="my-2 overflow-x-auto rounded-md border bg-muted/20 px-3 py-2">
        <p className="text-[10px] text-muted-foreground mb-1">公式</p>
        <code className="text-sm font-mono whitespace-pre-wrap break-all text-foreground/90">
          {formulaText || block.content}
        </code>
      </div>
    );
  }

  if (block.type === "image") {
    const canShowImage = kbId && docId && block.image_url;
    // 优先使用 VLM 视觉模型描述，OCR 原始结果不再在前端展示
    const vlmDesc = block.image_description || "";
    // 从 content 中提取图片描述（去掉 OCR 后缀）
    const descFromContent = block.content
      .replace(/^\[图片描述\]\s*/, "")
      .replace(/\n\[OCR\].*$/s, "")
      .replace(/^\[图片文字\]\s*/, "")
      .replace(/^\[图片\]\s*/, "")
      .trim();
    const bestDesc = vlmDesc || descFromContent || "";

    return (
      <div className="space-y-2">
        {!compact && <p className="text-xs text-muted-foreground">图片</p>}
        {canShowImage && (
          <AuthenticatedImage
            kbId={kbId}
            docId={docId}
            imageUrl={block.image_url}
            alt={block.section_title || block.image_caption || "文档图片"}
            className={compact ? "max-h-48" : undefined}
            imageWidth={block.image_width}
            imageHeight={block.image_height}
          />
        )}
        {block.image_caption && (
          <p className="text-xs font-medium text-foreground/80">
            {block.image_caption}
          </p>
        )}
        {bestDesc && bestDesc !== "未识别到文字" && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {bestDesc}
          </p>
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

/** 参考文献卡片 —— 解析 embed_content 中的结构化字段并格式化展示 */
function ReferenceCard({ content, compact }: { content: string; compact?: boolean }) {
  // 解析 embed_content 中的结构化字段
  const refId = content.match(/^\[参考文献\s*(\S+)\]/m)?.[1] || "";
  const authors = content.match(/^作者:\s*(.+)$/m)?.[1]?.trim() || "";
  const title = content.match(/^标题:\s*(.+)$/m)?.[1]?.trim() || "";
  const year = content.match(/^年份:\s*(.+)$/m)?.[1]?.trim() || "";
  // raw_text 在最后一个字段之后
  const lastMetaIdx = Math.max(
    content.lastIndexOf("作者:"),
    content.lastIndexOf("标题:"),
    content.lastIndexOf("年份:"),
    content.lastIndexOf(`[参考文献 ${refId}]`),
  );
  const rawText = lastMetaIdx >= 0
    ? content.slice(content.indexOf("\n", lastMetaIdx) + 1).trim()
    : content;

  const citation = [authors, year].filter(Boolean).join(" · ");

  if (compact) {
    return (
      <div className="flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs">
        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
          [{refId}]
        </span>
        <div className="min-w-0">
          {title && <p className="font-medium truncate">{title}</p>}
          {citation && <p className="text-muted-foreground">{citation}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md border bg-muted/10 px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="shrink-0 rounded bg-primary/10 px-2 py-0.5 text-[11px] font-mono font-medium text-primary">
          [{refId}]
        </span>
        {year && (
          <span className="text-[11px] text-muted-foreground">{year}</span>
        )}
      </div>
      {title && (
        <p className="text-sm font-medium leading-snug">{title}</p>
      )}
      {authors && (
        <p className="text-xs text-muted-foreground">{authors}</p>
      )}
      <details className="mt-1">
        <summary className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground select-none">
          完整引用
        </summary>
        <p className="mt-1 text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap border-l-2 border-muted pl-2">
          {rawText || content}
        </p>
      </details>
    </div>
  );
}
