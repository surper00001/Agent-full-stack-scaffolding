import { Link } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { KBBlockRenderer } from "@/components/kb/kb-block-renderer";
import type { KBBlockData } from "@/components/kb/kb-block-renderer";
import type { KBSearchResultItem } from "@/types";

interface SearchResultCardProps {
  item: KBSearchResultItem;
  kbId: string;
  expanded: boolean;
  onToggleExpand: () => void;
}

const CHUNK_TYPE_LABEL: Record<string, string> = {
  table: "表格",
  image: "图片",
  code: "代码",
  text: "文本",
  reference: "参考文献",
  formula: "公式",
};

export function SearchResultCard({ item, kbId, expanded, onToggleExpand }: SearchResultCardProps) {
  const scorePercent = Math.round(item.score * 100);
  const isLowScore = scorePercent < 30;
  const parentContext = item.metadata_?.parent_context || item.expanded_content;

  return (
    <Card className="group">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <div className="min-w-0">
              <p className="text-sm font-medium truncate">{item.document_filename}</p>
              <p className="text-xs text-muted-foreground flex flex-wrap items-center gap-1">
                <span>
                  第 {item.page_start}
                  {item.page_start !== item.page_end ? `-${item.page_end}` : ""} 页
                </span>
                {item.metadata_?.section_title && (
                  <span>· {item.metadata_.section_title}</span>
                )}
                <span
                  className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] ${
                    isLowScore
                      ? "bg-muted text-muted-foreground"
                      : "bg-primary/10 text-primary"
                  }`}
                >
                  相关度 {scorePercent}%
                  {isLowScore && " · 低相关"}
                </span>
                <span className="inline-flex items-center rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {CHUNK_TYPE_LABEL[item.chunk_type] || "文本"}
                </span>
              </p>
            </div>
          </div>
          <Link
            to={`/kb/${kbId}/documents/${item.document_id}`}
            className="text-xs text-primary hover:underline shrink-0 ml-2"
          >
            查看原文
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <KBBlockRenderer
          block={{
            type: item.chunk_type,
            content: item.content,
            table_html: item.metadata_?.table_html,
            image_url: item.metadata_?.image_url,
            is_table_image: item.metadata_?.is_table_image ?? null,
            table_caption: item.metadata_?.table_caption ?? null,
            ocr_status: item.metadata_?.ocr_status as KBBlockData["ocr_status"],
            ocr_error: item.metadata_?.ocr_error,
            image_caption: item.metadata_?.image_caption,
            image_description: item.metadata_?.image_description,
            section_title: item.metadata_?.section_title,
            image_width: item.metadata_?.image_width ?? null,
            image_height: item.metadata_?.image_height ?? null,
          }}
          kbId={kbId}
          docId={item.document_id}
          compact
        />

        {(item.context_before || item.context_after || parentContext) && (
          <div>
            <button
              type="button"
              onClick={onToggleExpand}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
              {expanded ? "收起上下文" : "展开上下文"}
            </button>
            {expanded && (
              <div className="mt-2 space-y-2 pl-3 border-l-2 border-muted">
                {parentContext && (
                  <div className="text-sm text-muted-foreground">
                    <p className="text-xs font-medium text-muted-foreground/60 mb-1">父块上下文</p>
                    <p className="whitespace-pre-wrap">{parentContext}</p>
                  </div>
                )}
                {item.context_before && (
                  <div className="text-sm text-muted-foreground">
                    <p className="text-xs font-medium text-muted-foreground/60 mb-1">上文</p>
                    <p className="whitespace-pre-wrap">{item.context_before}</p>
                  </div>
                )}
                {item.context_after && (
                  <div className="text-sm text-muted-foreground">
                    <p className="text-xs font-medium text-muted-foreground/60 mb-1">下文</p>
                    <p className="whitespace-pre-wrap">{item.context_after}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
