/**
 * 混合内容消息渲染 —— 解析 [图片:N] [表格:N] [代码:N] 标记，内联渲染到聊天消息中。
 */
import { type ReactNode } from "react";
import { Table, FileCode } from "lucide-react";
import { AuthenticatedImage } from "./authenticated-image";
import type { KBCitation } from "./citation-cards";

// ── 工具 ──────────────────────────────────────────────────

function parseKbImageUrl(
  imageUrl: string,
): { kbId: string; docId: string } | null {
  const m = imageUrl.match(
    /\/knowledge-bases\/([^/]+)\/documents\/([^/]+)(?:\/images\/|\/download)/,
  );
  if (!m) return null;
  return { kbId: m[1], docId: m[2] };
}

type MarkerKind = "image" | "table" | "code";

interface MarkerMatch {
  kind: MarkerKind;
  citeNum: number;
  startIndex: number;
  endIndex: number;
}

/** 从文本中提取所有标记（按位置排序） */
function findAllMarkers(text: string): MarkerMatch[] {
  const markers: MarkerMatch[] = [];
  const patterns: { kind: MarkerKind; re: RegExp }[] = [
    { kind: "image", re: /\[图片:(\d+)\]/g },
    { kind: "table", re: /\[表格:(\d+)\]/g },
    { kind: "code", re: /\[代码:(\d+)\]/g },
  ];

  for (const { kind, re } of patterns) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      markers.push({
        kind,
        citeNum: parseInt(m[1], 10),
        startIndex: m.index,
        endIndex: m.index + m[0].length,
      });
    }
  }

  markers.sort((a, b) => a.startIndex - b.startIndex);
  return markers;
}

// ── 子组件 ───────────────────────────────────────────────

/** 内联表格渲染（使用 table_html，回退 markdown 表格） */
function InlineTable({ cite, citeNum }: { cite: KBCitation; citeNum: number }) {
  // 优先使用 HTML
  if (cite.table_html) {
    return (
      <div className="my-3 space-y-1">
        <div className="flex items-center gap-1.5 mb-1">
          <Table className="h-3.5 w-3.5 text-orange-500" />
          <span className="text-[10px] font-medium text-orange-600 dark:text-orange-400">
            表格 {citeNum}
          </span>
        </div>
        <div
          className="overflow-x-auto rounded-md border bg-background/80 text-xs"
          dangerouslySetInnerHTML={{
            __html: cite.table_html
              .replace(/<table/g, '<table class="w-full border-collapse"')
              .replace(/<td/g, '<td class="border px-2 py-1"')
              .replace(/<th/g, '<th class="border px-2 py-1 bg-muted/50 font-medium"'),
          }}
        />
        {cite.table_caption && (
          <p className="text-[10px] text-muted-foreground text-center">
            {cite.table_caption}
          </p>
        )}
        <p className="text-[10px] text-muted-foreground/60 text-center">
          {cite.source} · 第{cite.page}页
        </p>
      </div>
    );
  }

  // 回退：markdown 表格转 HTML
  const rows = cite.content
    .split("\n")
    .filter((r) => r.trim().startsWith("|"))
    .map((r) =>
      r
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((c) => c.trim()),
    );

  if (rows.length < 2) return null;
  const [header, sep, ...data] = rows;

  return (
    <div className="my-3 space-y-1">
      <div className="flex items-center gap-1.5 mb-1">
        <Table className="h-3.5 w-3.5 text-orange-500" />
        <span className="text-[10px] font-medium text-orange-600 dark:text-orange-400">
          表格 {citeNum}
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border bg-background/80">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              {header.map((h, i) => (
                <th key={i} className="border px-2 py-1 bg-muted/50 font-medium text-left">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.filter((r) => !r.every((c) => /^-{3,}$/.test(c))).map((row, ri) => (
              <tr key={ri}>
                {row.map((c, ci) => (
                  <td key={ci} className="border px-2 py-1">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-muted-foreground/60 text-center">
        {cite.source} · 第{cite.page}页
      </p>
    </div>
  );
}

/** 内联代码块渲染 */
function InlineCode({ cite, citeNum }: { cite: KBCitation; citeNum: number }) {
  return (
    <div className="my-3 space-y-1">
      <div className="flex items-center gap-1.5 mb-1">
        <FileCode className="h-3.5 w-3.5 text-emerald-500" />
        <span className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
          代码 {citeNum}
        </span>
      </div>
      <pre className="overflow-x-auto rounded-md border bg-zinc-950 p-3 text-xs text-zinc-200 leading-relaxed">
        <code>{cite.content}</code>
      </pre>
      <p className="text-[10px] text-muted-foreground/60 text-center">
        {cite.source} · 第{cite.page}页
      </p>
    </div>
  );
}

/** 内联图片渲染 */
function InlineImage({ cite, citeNum }: { cite: KBCitation; citeNum: number }) {
  if (!cite.image_url) return null;
  const parsed = parseKbImageUrl(cite.image_url);
  if (!parsed) return null;

  return (
    <div className="my-3 space-y-1">
      <AuthenticatedImage
        kbId={parsed.kbId}
        docId={parsed.docId}
        imageUrl={cite.image_url}
        alt={cite.image_caption || cite.image_description || `图片 ${citeNum}`}
        imageWidth={cite.image_width}
        imageHeight={cite.image_height}
        className="max-w-full"
      />
      {(cite.image_caption || cite.image_description) && (
        <p className="text-[11px] text-muted-foreground text-center">
          {cite.image_caption && (
            <span className="font-medium">{cite.image_caption}</span>
          )}
          {cite.image_caption && cite.image_description && " — "}
          {cite.image_description && (
            <span>{cite.image_description.slice(0, 120)}</span>
          )}
        </p>
      )}
      <p className="text-[10px] text-muted-foreground/60 text-center">
        {cite.source} · 第{cite.page}页
      </p>
    </div>
  );
}

// ── 主组件 ───────────────────────────────────────────────

interface InlineContentMessageProps {
  text: string;
  citations?: KBCitation[];
  renderMarkdown: (text: string) => ReactNode;
}

export function InlineImageMessage({
  text,
  citations,
  renderMarkdown,
}: InlineContentMessageProps) {
  if (!citations || citations.length === 0) {
    return <>{renderMarkdown(text)}</>;
  }

  const markers = findAllMarkers(text);
  if (markers.length === 0) {
    return <>{renderMarkdown(text)}</>;
  }

  const citeByIndex = new Map<number, KBCitation>();
  citations.forEach((c, i) => citeByIndex.set(i + 1, c));

  const segments: ReactNode[] = [];
  let lastIndex = 0;
  let segKey = 0;

  for (const marker of markers) {
    // 标记前的文本
    if (marker.startIndex > lastIndex) {
      const before = text.slice(lastIndex, marker.startIndex).trimEnd();
      if (before) {
        segments.push(
          <span key={`txt-${segKey++}`}>{renderMarkdown(before)}</span>,
        );
      }
    }

    // 渲染标记对应的内容
    const cite = citeByIndex.get(marker.citeNum);
    if (cite) {
      switch (marker.kind) {
        case "image":
          if (cite.image_url) {
            segments.push(
              <InlineImage key={`img-${segKey++}`} cite={cite} citeNum={marker.citeNum} />,
            );
          } else {
            segments.push(
              <span key={`fb-${segKey++}`} className="text-muted-foreground italic text-xs">
                {text.slice(marker.startIndex, marker.endIndex)}
              </span>,
            );
          }
          break;
        case "table":
          segments.push(
            <InlineTable key={`tbl-${segKey++}`} cite={cite} citeNum={marker.citeNum} />,
          );
          break;
        case "code":
          segments.push(
            <InlineCode key={`cod-${segKey++}`} cite={cite} citeNum={marker.citeNum} />,
          );
          break;
      }
    } else {
      // 找不到引用 — 保留原始标记
      segments.push(
        <span key={`fb-${segKey++}`} className="text-muted-foreground italic text-xs">
          {text.slice(marker.startIndex, marker.endIndex)}
        </span>,
      );
    }

    lastIndex = marker.endIndex;
  }

  // 最后一段文本
  if (lastIndex < text.length) {
    const after = text.slice(lastIndex);
    if (after.trim()) {
      segments.push(
        <span key={`txt-${segKey++}`}>{renderMarkdown(after)}</span>,
      );
    }
  }

  return <>{segments}</>;
}
