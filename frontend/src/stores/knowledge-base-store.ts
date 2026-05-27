import { create } from "zustand";
import type {
  KBDocumentListItem,
  KBSearchRequest,
  KBSearchResponse,
  KnowledgeBase,
  KnowledgeBaseListItem,
} from "@/types";
import * as kbApi from "@/api/knowledge-base";

export interface UploadProgress {
  docId: string;
  filename: string;
  stage: string;
  stageLabel: string;
  percentage: number;
  estimatedSeconds: number | null;
  errorMessage: string | null;
  totalPages?: number;
  parsedPages?: number;
  totalChunks?: number;
  embeddedChunks?: number;
}

interface KBStore {
  kbList: KnowledgeBaseListItem[];
  kbTotal: number;
  kbLoading: boolean;
  kbError: string | null;

  currentKB: KnowledgeBase | null;
  currentKBLoading: boolean;

  documents: KBDocumentListItem[];
  docTotal: number;
  docLoading: boolean;

  searchResult: KBSearchResponse | null;
  searchLoading: boolean;
  searchError: string | null;

  uploadProgressMap: Record<string, UploadProgress>;
  indexNeedsReindex: boolean;

  fetchKBList: (page?: number, pageSize?: number) => Promise<void>;
  fetchKB: (id: string) => Promise<void>;
  createKB: (name: string, description?: string) => Promise<KnowledgeBase>;
  updateKB: (id: string, updates: {
    name?: string;
    description?: string;
    embedding_model?: string;
    reranker_model?: string;
  }) => Promise<void>;
  syncKBModelsFromServer: (id: string) => Promise<void>;
  deleteKB: (id: string) => Promise<void>;

  fetchDocuments: (kbId: string, page?: number, pageSize?: number) => Promise<void>;
  uploadDocument: (kbId: string, file: File) => Promise<{ docId: string }>;
  deleteDocument: (kbId: string, docId: string) => Promise<void>;
  cancelDocument: (kbId: string, docId: string) => Promise<void>;
  retryDocument: (kbId: string, docId: string, filename: string) => Promise<void>;
  reprocessDocument: (kbId: string, docId: string, filename: string) => Promise<void>;
  pollProgress: (kbId: string, docId: string, filename: string) => Promise<void>;
  resumePollingForProcessing: (kbId: string) => void;
  clearUploadProgress: (docId?: string) => void;

  search: (kbId: string, req: KBSearchRequest) => Promise<void>;
  clearSearch: () => void;

  checkIndexStatus: (kbId: string) => Promise<void>;
  reindexKB: (kbId: string) => Promise<void>;
}

export const useKBStore = create<KBStore>((set, get) => ({
  kbList: [],
  kbTotal: 0,
  kbLoading: false,
  kbError: null,

  currentKB: null,
  currentKBLoading: false,

  documents: [],
  docTotal: 0,
  docLoading: false,

  searchResult: null,
  searchLoading: false,
  searchError: null,

  uploadProgressMap: {},
  indexNeedsReindex: false,

  fetchKBList: async (page = 1, pageSize = 20) => {
    set({ kbLoading: true, kbError: null });
    try {
      const res = await kbApi.listKBs({ page, page_size: pageSize });
      set({ kbList: res.data.items, kbTotal: res.data.total, kbLoading: false });
    } catch (err) {
      set({ kbError: (err as Error).message, kbLoading: false });
    }
  },

  fetchKB: async (id: string) => {
    set({ currentKBLoading: true });
    try {
      const res = await kbApi.getKB(id);
      set({
        currentKB: res.data,
        currentKBLoading: false,
        indexNeedsReindex: res.data.needs_reindex ?? false,
      });
    } catch (err) {
      set({ kbError: (err as Error).message, currentKBLoading: false });
    }
  },

  createKB: async (name, description) => {
    try {
      const res = await kbApi.createKB(name, description);
      set({ kbList: [...get().kbList, res.data] });
      return res.data;
    } catch (err) {
      set({ kbError: (err as Error).message });
      throw err;
    }
  },

  updateKB: async (id, updates) => {
    try {
      const res = await kbApi.updateKB(id, updates);
      set({
        kbList: get().kbList.map((k) => (k.id === id ? { ...k, ...res.data } : k)),
        currentKB: get().currentKB?.id === id ? res.data : get().currentKB,
      });
    } catch (err) {
      set({ kbError: (err as Error).message });
      throw err;
    }
  },

  syncKBModelsFromServer: async (id) => {
    const kb = get().currentKB;
    if (!kb?.server_embedding_model || !kb?.server_reranker_model) {
      await get().fetchKB(id);
    }
    const current = get().currentKB;
    if (!current?.server_embedding_model || !current.server_reranker_model) {
      throw new Error("无法读取服务端默认模型配置");
    }
    await get().updateKB(id, {
      embedding_model: current.server_embedding_model,
      reranker_model: current.server_reranker_model,
    });
    await get().fetchKB(id);
    set({ indexNeedsReindex: true });
  },

  deleteKB: async (id) => {
    try {
      await kbApi.deleteKB(id);
      set({
        kbList: get().kbList.filter((k) => k.id !== id),
        currentKB: get().currentKB?.id === id ? null : get().currentKB,
      });
    } catch (err) {
      set({ kbError: (err as Error).message });
    }
  },

  fetchDocuments: async (kbId, page = 1, pageSize = 50) => {
    set({ docLoading: true });
    try {
      const res = await kbApi.listDocuments(kbId, { page, page_size: pageSize });
      set({ documents: res.data.items, docTotal: res.data.total, docLoading: false });

      // 恢复失败/卡住文档的错误进度（刷新页面后 progress 内存会丢失）
      for (const doc of res.data.items) {
        const failed =
          doc.status === "error" ||
          Boolean(doc.error_message) ||
          doc.status === "processing";
        if (!failed || get().uploadProgressMap[doc.id]) continue;
        try {
          const progRes = await kbApi.getDocumentProgress(kbId, doc.id);
          const p = progRes.data;
          if (p && (p.stage === "error" || doc.status === "error" || doc.error_message)) {
            set((s) => ({
              uploadProgressMap: {
                ...s.uploadProgressMap,
                [doc.id]: {
                  docId: doc.id,
                  filename: doc.filename,
                  stage: p.stage === "error" ? "error" : p.stage,
                  stageLabel: p.stage_label,
                  percentage: p.percentage,
                  estimatedSeconds: p.estimated_seconds,
                  errorMessage: p.error_message ?? doc.error_message ?? null,
                  totalPages: p.total_pages,
                  parsedPages: p.parsed_pages,
                  totalChunks: p.total_chunks,
                  embeddedChunks: p.embedded_chunks,
                },
              },
            }));
          }
        } catch {
          if (doc.status === "error" || doc.error_message) {
            set((s) => ({
              uploadProgressMap: {
                ...s.uploadProgressMap,
                [doc.id]: {
                  docId: doc.id,
                  filename: doc.filename,
                  stage: "error",
                  stageLabel: "处理失败",
                  percentage: 100,
                  estimatedSeconds: null,
                  errorMessage: doc.error_message ?? "未知错误",
                },
              },
            }));
          }
        }
      }
    } catch (err) {
      set({ kbError: (err as Error).message, docLoading: false });
    }
  },

  uploadDocument: async (kbId, file) => {
    const tempId = `upload_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    // 立即显示上传进度卡片
    set((s) => ({
      uploadProgressMap: {
        ...s.uploadProgressMap,
        [tempId]: {
          docId: tempId,
          filename: file.name,
          stage: "uploading",
          stageLabel: "上传文件中",
          percentage: 0,
          estimatedSeconds: null,
          errorMessage: null,
        },
      },
    }));
    try {
      const res = await kbApi.uploadDocument(kbId, file, (pct) => {
        set((s) => {
          const entry = s.uploadProgressMap[tempId];
          if (!entry) return s;
          return {
            uploadProgressMap: {
              ...s.uploadProgressMap,
              [tempId]: { ...entry, percentage: pct },
            },
          };
        });
      });
      const docId = res.data.document_id;
      // 将临时条目替换为真实 docId 条目，切换到轮询阶段
      set((s) => {
        const next = { ...s.uploadProgressMap };
        delete next[tempId];
        next[docId] = {
          docId,
          filename: file.name,
          stage: "uploaded",
          stageLabel: "上传完成，等待处理",
          percentage: 100,
          estimatedSeconds: null,
          errorMessage: null,
        };
        return { uploadProgressMap: next };
      });
      get().pollProgress(kbId, docId, file.name);
      return { docId };
    } catch (err) {
      set((s) => {
        const next = { ...s.uploadProgressMap };
        const temp = next[tempId];
        delete next[tempId];
        if (temp) {
          next[tempId] = {
            ...temp,
            stage: "error",
            stageLabel: "上传失败",
            errorMessage: (err as Error).message || "文件上传失败",
          };
        }
        return { uploadProgressMap: next };
      });
      throw err;
    }
  },

  deleteDocument: async (kbId, docId) => {
    try {
      await kbApi.deleteDocument(kbId, docId);
      // 清除上传进度卡片
      get().clearUploadProgress(docId);
      await get().fetchDocuments(kbId);
      await get().fetchKB(kbId);
    } catch (err) {
      set({ kbError: (err as Error).message });
    }
  },

  cancelDocument: async (kbId, docId) => {
    try {
      const res = await kbApi.cancelDocument(kbId, docId);
      if (res.data.cancelled) {
        set((s) => {
          const entry = s.uploadProgressMap[docId];
          if (!entry) return s;
          return {
            uploadProgressMap: {
              ...s.uploadProgressMap,
              [docId]: { ...entry, stage: "cancelled", stageLabel: "已取消" },
            },
          };
        });
        // 稍后刷新文档列表
        setTimeout(() => {
          get().fetchDocuments(kbId);
        }, 1500);
      }
    } catch (err) {
      set({ kbError: (err as Error).message });
    }
  },

  retryDocument: async (kbId, docId, filename) => {
    try {
      await kbApi.retryDocument(kbId, docId);
      await get().pollProgress(kbId, docId, filename);
      await get().fetchDocuments(kbId);
    } catch (err) {
      set({ kbError: (err as Error).message });
      throw err;
    }
  },

  reprocessDocument: async (kbId, docId, filename) => {
    try {
      await kbApi.reprocessDocument(kbId, docId);
      await get().pollProgress(kbId, docId, filename);
      await get().fetchDocuments(kbId);
    } catch (err) {
      set({ kbError: (err as Error).message });
      throw err;
    }
  },

  pollProgress: async (kbId, docId, filename) => {
    const poll = async () => {
      try {
        const res = await kbApi.getDocumentProgress(kbId, docId);
        const progress = res.data;
        if (!progress) {
          // 后端尚未开始处理，保留当前卡片，短暂后重试
          setTimeout(poll, 800);
          return;
        }

        set((s) => ({
          uploadProgressMap: {
            ...s.uploadProgressMap,
            [docId]: {
              docId,
              filename,
              stage: progress.stage,
              stageLabel: progress.stage_label,
              percentage: progress.percentage,
              estimatedSeconds: progress.estimated_seconds,
              errorMessage: progress.error_message,
              totalPages: progress.total_pages,
              parsedPages: progress.parsed_pages,
              totalChunks: progress.total_chunks,
              embeddedChunks: progress.embedded_chunks,
            },
          },
        }));

        if (progress.stage === "ready") {
          setTimeout(() => {
            get().fetchDocuments(kbId);
            get().fetchKB(kbId);
            get().clearUploadProgress(docId);
          }, 1500);
          return;
        }

        if (progress.stage === "error" || progress.stage === "cancelled") {
          get().fetchDocuments(kbId);
          return;
        }

        const intervals: Record<string, number> = {
          uploaded: 1000, analyzing: 800, parsing: 800,
          chunking: 500, embedding: 1000, indexing: 1500,
        };
        setTimeout(poll, intervals[progress.stage] || 1000);
      } catch {
        // 网络瞬时错误 — 2 秒后重试，不删除进度卡片
        setTimeout(poll, 2000);
      }
    };
    poll();
  },

  resumePollingForProcessing: (kbId) => {
    const processing = get().documents.filter((d) => d.status === "processing" || d.status === "uploading");
    for (const doc of processing) {
      if (!get().uploadProgressMap[doc.id]) {
        get().pollProgress(kbId, doc.id, doc.filename);
      }
    }
  },

  clearUploadProgress: (docId) => {
    if (!docId) {
      set({ uploadProgressMap: {} });
      return;
    }
    set((s) => {
      const next = { ...s.uploadProgressMap };
      delete next[docId];
      return { uploadProgressMap: next };
    });
  },

  search: async (kbId, req) => {
    set({ searchLoading: true, searchError: null });
    try {
      const res = await kbApi.searchKB(kbId, req);
      set({ searchResult: res.data, searchLoading: false });
    } catch (err) {
      set({ searchError: (err as Error).message, searchLoading: false });
    }
  },

  clearSearch: () => set({ searchResult: null, searchError: null }),

  checkIndexStatus: async (kbId) => {
    const kb = get().currentKB;
    if (kb?.id === kbId && kb.needs_reindex !== undefined) {
      set({ indexNeedsReindex: kb.needs_reindex });
      return;
    }
    try {
      const res = await kbApi.getIndexStatus(kbId);
      set({ indexNeedsReindex: res.data.needs_reindex });
    } catch {
      set({ indexNeedsReindex: false });
    }
  },

  reindexKB: async (kbId) => {
    try {
      await kbApi.reindexKB(kbId);
      set({ indexNeedsReindex: false });
    } catch (err) {
      set({ kbError: (err as Error).message });
      throw err;
    }
  },
}));
