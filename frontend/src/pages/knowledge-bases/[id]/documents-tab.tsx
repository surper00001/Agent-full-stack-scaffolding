import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import type { KBDocumentListItem } from "@/types";
import type { UploadProgress } from "@/stores/knowledge-base-store";
import { UploadZone } from "@/components/kb/upload-zone";
import { ProcessingProgressCard } from "@/components/kb/processing-progress-card";
import { DocumentListItem } from "@/components/kb/document-list-item";

interface DocumentsTabProps {
  documents: KBDocumentListItem[];
  loading: boolean;
  uploading: boolean;
  uploadProgressMap: Record<string, UploadProgress>;
  kbId: string;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onCancel: (docId: string) => void;
  onDelete: (docId: string, filename: string) => Promise<void>;
  onRetry: (docId: string, filename: string) => Promise<void>;
  onReprocess: (docId: string, filename: string) => Promise<void>;
  onRefresh: () => void;
}

export function DocumentsTab({
  documents,
  loading,
  uploading,
  uploadProgressMap,
  kbId,
  fileInputRef,
  onUpload,
  onCancel,
  onDelete,
  onRetry,
  onReprocess,
  onRefresh,
}: DocumentsTabProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="shrink-0 space-y-4">
        <UploadZone uploading={uploading} fileInputRef={fileInputRef} onUpload={onUpload} />

        {Object.values(uploadProgressMap).map((p) => (
          <ProcessingProgressCard
            key={p.docId}
            progress={p}
            onCancel={() => onCancel(p.docId)}
            onDelete={() => onDelete(p.docId, p.filename)}
            onRetry={() => onRetry(p.docId, p.filename)}
            onReprocess={() => onReprocess(p.docId, p.filename)}
          />
        ))}

        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">已上传文档 ({documents.length})</h3>
          <Button variant="ghost" size="sm" onClick={onRefresh}>
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            刷新
          </Button>
        </div>
      </div>

      <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden pr-1">
        {loading ? (
          <LoadingSpinner size="sm" />
        ) : documents.length === 0 ? (
          <EmptyState title="暂无文档" description="上传你的第一个文档开始构建知识库" />
        ) : (
          <div className="space-y-2 pb-4">
            {documents.map((doc) => (
              <DocumentListItem
                key={doc.id}
                doc={doc}
                kbId={kbId}
                onDelete={onDelete}
                onReprocess={onReprocess}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
