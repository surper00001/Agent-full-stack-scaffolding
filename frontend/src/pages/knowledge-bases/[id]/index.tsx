import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useKBStore } from "@/stores";
import { useConfirm } from "@/hooks/use-confirm";
import { useToast } from "@/components/ui/use-toast";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { KBDetailHeader } from "./kb-detail-header";
import { KBDetailTabs, type KBDetailTab } from "./kb-detail-tabs";
import { DocumentsTab } from "./documents-tab";
import { SearchTab } from "./search-tab";

export default function KnowledgeBaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const kbId = id!;

  const {
    currentKB,
    currentKBLoading,
    fetchKB,
    documents,
    docLoading,
    fetchDocuments,
    uploadDocument,
    deleteDocument,
    cancelDocument,
    retryDocument,
    reprocessDocument,
    searchResult,
    searchLoading,
    searchError,
    search,
    clearSearch,
    uploadProgressMap,
    resumePollingForProcessing,
    indexNeedsReindex,
    reindexKB,
    syncKBModelsFromServer,
    kbError,
  } = useKBStore();

  const [tab, setTab] = useState<KBDetailTab>("documents");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const confirm = useConfirm();
  const { toast } = useToast();

  useEffect(() => {
    fetchKB(kbId);
    fetchDocuments(kbId, 1, 50);
  }, [kbId, fetchKB, fetchDocuments]);

  useEffect(() => {
    if (documents.length > 0) {
      resumePollingForProcessing(kbId);
    }
  }, [documents, kbId, resumePollingForProcessing]);

  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;
      setUploading(true);
      for (const file of Array.from(files)) {
        try {
          await uploadDocument(kbId, file);
        } catch {
          // 单个文件上传失败 — 进度卡片已展示错误，继续处理剩余文件
        }
      }
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [kbId, uploadDocument],
  );

  const handleDelete = async (docId: string, filename: string) => {
    if (!await confirm({ description: `确定删除「${filename}」？`, variant: "destructive" })) return;
    await deleteDocument(kbId, docId);
  };

  const handleCancel = useCallback(
    (docId: string) => {
      cancelDocument(kbId, docId);
    },
    [kbId, cancelDocument],
  );

  const handleRetry = async (docId: string, filename: string) => {
    try {
      await retryDocument(kbId, docId, filename);
    } catch {
      // kbError 已写入 store
    }
  };

  const handleReprocess = async (docId: string, filename: string) => {
    try {
      await reprocessDocument(kbId, docId, filename);
    } catch {
      // kbError 已写入 store
    }
  };

  const handleReindex = async () => {
    if (!await confirm({ description: "将使用当前 Embedding 模型重建全部向量索引，是否继续？" })) return;
    await reindexKB(kbId);
    toast({ title: "重建索引任务已启动，请稍后刷新" });
  };

  const handleSyncModels = async () => {
    if (
      !await confirm({
        description: "将把此知识库的 Embedding / Reranker 切换为服务端默认（千问），之后需重建索引。是否继续？",
      })
    ) {
      return;
    }
    try {
      await syncKBModelsFromServer(kbId);
      toast({ title: "模型已切换，请点击「重建索引」后再检索" });
    } catch {
      // kbError 已写入 store
    }
  };

  if (currentKBLoading) return <LoadingSpinner size="lg" className="mt-12" />;
  if (!currentKB) return <EmptyState title="知识库不存在" description="该知识库可能已被删除" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <KBDetailHeader
        kb={currentKB}
        kbError={kbError}
        indexNeedsReindex={indexNeedsReindex}
        onChat={() => navigate(`/chat?kb=${kbId}&mode=agent`)}
        onReindex={handleReindex}
        onSyncModels={handleSyncModels}
      />

      <KBDetailTabs tab={tab} onChange={setTab} />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {tab === "documents" ? (
        <DocumentsTab
          documents={documents}
          loading={docLoading}
          uploading={uploading}
          uploadProgressMap={uploadProgressMap}
          kbId={kbId}
          fileInputRef={fileInputRef}
          onUpload={handleUpload}
          onCancel={handleCancel}
          onDelete={handleDelete}
          onRetry={handleRetry}
          onReprocess={handleReprocess}
          onRefresh={() => {
            fetchDocuments(kbId, 1, 50);
            fetchKB(kbId);
          }}
        />
      ) : (
        <SearchTab
          kbId={kbId}
          searchResult={searchResult}
          searchLoading={searchLoading}
          searchError={searchError}
          onSearch={(query, topK, rerank, filters) => search(kbId, { query, top_k: topK, rerank, filters })}
          onClear={clearSearch}
          onChatWithQuery={(q) => navigate(`/chat?kb=${kbId}&mode=agent&q=${encodeURIComponent(q)}`)}
        />
      )}
      </div>
    </div>
  );
}
