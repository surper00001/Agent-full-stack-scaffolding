/**
 * 知识库引用卡片——展示 Agent search_knowledge_base 工具返回的检索结果。
 *
 * tool_result JSON 结构：{ results: [{ content, source, page, score, section_title, chunk_id }] }
 */
import { useState } from "react";
import { BookOpen, FileText } from "lucide-react";

export interface KBCitation {
  chunk_id?: string;
  content: string;
  source: string;
  page: number;
  score: number;
  section_title?: string;
}

interface CitationCardsProps {
  citations: KBCitation[];
}

export function CitationCards({ citations }: CitationCardsProps) {
  const [expanded, setExpanded] = useState(false);
  const displayCitations = expanded ? citations : citations.slice(0, 3);

  if (citations.length === 0) return null;

  return (
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
          {displayCitations.map((cite, i) => (
            <div
              key={cite.chunk_id || i}
              className="flex items-start gap-2 rounded-lg border bg-background/60 p-2.5 text-xs hover:border-primary/30 transition-colors"
            >
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-blue-100 dark:bg-blue-900/30 text-[10px] font-bold text-blue-700 dark:text-blue-400">
                {i + 1}
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
          ))}
        </div>
      </div>
    </div>
  );
}

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
    }));
  } catch {
    return [];
  }
}
