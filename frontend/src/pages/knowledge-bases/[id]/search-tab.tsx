import { useState } from "react";
import { Search, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { SearchResultCard } from "@/components/kb/search-result-card";
import type { KBSearchRequest, KBSearchResponse } from "@/types";

interface SearchTabProps {
  kbId: string;
  searchResult: KBSearchResponse | null;
  searchLoading: boolean;
  searchError: string | null;
  onSearch: (
    query: string,
    topK: number,
    rerank: boolean,
    filters?: KBSearchRequest["filters"],
  ) => Promise<void>;
  onClear: () => void;
  onChatWithQuery: (query: string) => void;
}

export function SearchTab({
  kbId,
  searchResult,
  searchLoading,
  searchError,
  onSearch,
  onClear,
  onChatWithQuery,
}: SearchTabProps) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [rerank, setRerank] = useState(true);
  const [chunkType, setChunkType] = useState("");
  const [expandedChunk, setExpandedChunk] = useState<string | null>(null);

  const handleSearch = () => {
    if (!query.trim()) return;
    const filters = chunkType ? { chunk_type: chunkType as "text" | "table" | "image" } : undefined;
    onSearch(query.trim(), topK, rerank, filters);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {/* 检索工具栏固定，结果区独立滚动 */}
      <div className="shrink-0 space-y-3 rounded-lg border bg-card/50 p-4 shadow-sm">
        <div className="flex flex-wrap gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="输入查询内容，支持自然语言..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="pl-9"
            />
          </div>
          <select
            value={chunkType}
            onChange={(e) => setChunkType(e.target.value)}
            className="h-10 rounded-md border bg-background px-2 text-sm"
            title="分块类型过滤"
          >
            <option value="">全部类型</option>
            <option value="text">文本</option>
            <option value="table">表格</option>
            <option value="image">图片</option>
          </select>
          <select
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="h-10 rounded-md border bg-background px-3 text-sm"
          >
            {[3, 5, 10, 20].map((k) => (
              <option key={k} value={k}>
                {k} 条结果
              </option>
            ))}
          </select>
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={rerank}
              onChange={(e) => setRerank(e.target.checked)}
              className="rounded"
            />
            重排序
          </label>
          <Button onClick={handleSearch} disabled={searchLoading || !query.trim()}>
            {searchLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : "搜索"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          上传完成后在此测试召回；参数与 Agent 工具一致（top_k=5，Qwen3 Reranker 精排）
        </p>
        {searchError && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
            检索失败：{searchError}
          </div>
        )}
      </div>

      <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden pr-1">
        {searchLoading ? (
          <LoadingSpinner size="sm" className="mt-8" />
        ) : searchResult ? (
          <div className="space-y-3 pb-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
              <span>
                找到 {searchResult.results.length} 条相关结果
                {searchResult.total_found > searchResult.results.length &&
                  `（共召回 ${searchResult.total_found} 条）`}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-xs">{searchResult.reranked ? "已重排序" : "未重排序"}</span>
                <button
                  type="button"
                  onClick={() => onChatWithQuery(query)}
                  className="text-xs text-primary hover:underline"
                >
                  用此查询开聊
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    onClear();
                  }}
                  className="text-xs text-muted-foreground underline hover:text-foreground"
                >
                  清除结果
                </button>
              </div>
            </div>

            {searchResult.results.length === 0 ? (
              <EmptyState
                title="无匹配结果"
                description={
                  searchResult.reranked
                    ? "相关度低于阈值的结果已过滤，试试换关键词或关闭重排序"
                    : "试试换个关键词或调整查询方式"
                }
              />
            ) : (
              searchResult.results.map((item) => (
                <SearchResultCard
                  key={item.chunk_id}
                  item={item}
                  kbId={kbId}
                  expanded={expandedChunk === item.chunk_id}
                  onToggleExpand={() =>
                    setExpandedChunk(expandedChunk === item.chunk_id ? null : item.chunk_id)
                  }
                />
              ))
            )}
          </div>
        ) : (
          <EmptyState
            title="检索测试台"
            description="上传文档后在此验证 Qwen3 Embedding 召回效果；Agent 对话请使用「用此知识库对话」"
          />
        )}
      </div>
    </div>
  );
}
