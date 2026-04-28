import { Link } from "react-router-dom";
import { ArrowLeft, MessageSquare, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { KnowledgeBase } from "@/types";
import { formatFileSize } from "@/components/kb/constants";

interface KBDetailHeaderProps {
  kb: KnowledgeBase;
  kbError: string | null;
  indexNeedsReindex: boolean;
  onChat: () => void;
  onReindex: () => void;
  onSyncModels?: () => void;
}

export function KBDetailHeader({
  kb,
  kbError,
  indexNeedsReindex,
  onChat,
  onReindex,
  onSyncModels,
}: KBDetailHeaderProps) {
  return (
    <>
      <div className="flex items-center gap-4 flex-wrap">
        <Link to="/kb" className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold">{kb.name}</h1>
          {kb.description && <p className="text-sm text-muted-foreground">{kb.description}</p>}
        </div>
        <div className="flex flex-col items-end gap-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>{kb.document_count} 文档</span>
            <span>·</span>
            <span>{kb.total_chunks} 分块</span>
            <span>·</span>
            <span>{formatFileSize(kb.total_size_bytes)}</span>
          </div>
          <div className="max-w-md truncate text-right" title={`${kb.embedding_model} / ${kb.reranker_model}`}>
            Embedding: {kb.embedding_model.split("/").pop()}
            <span className="mx-1">·</span>
            Reranker: {kb.reranker_model.split("/").pop()}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onChat}>
          <MessageSquare className="mr-1 h-3.5 w-3.5" />
          用此知识库对话
        </Button>
      </div>

      {kbError && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
          {kbError}
        </div>
      )}

      {kb.models_differ_from_env && onSyncModels && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-blue-300 bg-blue-50/80 dark:bg-blue-950/20 px-4 py-3 text-sm">
          <div className="text-blue-900 dark:text-blue-100">
            此知识库仍绑定旧模型（如 BGE），与服务器默认（
            {kb.server_reranker_model?.split("/").pop() ?? "千问"}）不一致。检索会加载旧 Reranker，首次较慢。
          </div>
          <Button size="sm" variant="outline" onClick={onSyncModels}>
            切换为服务端默认
          </Button>
        </div>
      )}

      {indexNeedsReindex && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50/80 dark:bg-amber-950/20 px-4 py-3 text-sm">
          <div className="flex items-center gap-2 text-amber-800 dark:text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>Embedding 模型与向量索引不一致，请重建索引后再检索</span>
          </div>
          <Button size="sm" variant="outline" onClick={onReindex}>
            重建索引
          </Button>
        </div>
      )}
    </>
  );
}
