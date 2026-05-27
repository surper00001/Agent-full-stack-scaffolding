import client from "./client";
import { KB_SEARCH_TIMEOUT, KB_UPLOAD_TIMEOUT } from "@/lib/constants";
import type {
  ApiResponse,
  KBDocument,
  KBDocumentListItem,
  KBDocumentView,
  KBProcessProgress,
  KBSearchRequest,
  KBSearchResponse,
  KBUploadResponse,
  KnowledgeBase,
  KnowledgeBaseListItem,
  PaginatedResponse,
  PaginationParams,
} from "@/types";

const PATH = "/knowledge-bases";

// ====== 知识库 CRUD ======

export async function createKB(
  name: string,
  description?: string,
): Promise<ApiResponse<KnowledgeBase>> {
  const params = new URLSearchParams();
  params.set("name", name);
  if (description) params.set("description", description);
  const { data } = await client.post(`${PATH}?${params.toString()}`);
  return data;
}

export async function listKBs(
  params: PaginationParams,
): Promise<ApiResponse<PaginatedResponse<KnowledgeBaseListItem>>> {
  const { data } = await client.get(PATH, { params: { page: params.page, page_size: params.page_size } });
  return data;
}

export async function getKB(id: string): Promise<ApiResponse<KnowledgeBase>> {
  const { data } = await client.get(`${PATH}/${id}`);
  return data;
}

export async function updateKB(
  id: string,
  updates: {
    name?: string;
    description?: string;
    chunk_size?: number;
    chunk_overlap?: number;
    embedding_model?: string;
    reranker_model?: string;
  },
): Promise<ApiResponse<KnowledgeBase>> {
  const params = new URLSearchParams();
  if (updates.name) params.set("name", updates.name);
  if (updates.description !== undefined) params.set("description", updates.description);
  if (updates.chunk_size) params.set("chunk_size", String(updates.chunk_size));
  if (updates.chunk_overlap !== undefined) params.set("chunk_overlap", String(updates.chunk_overlap));
  if (updates.embedding_model) params.set("embedding_model", updates.embedding_model);
  if (updates.reranker_model) params.set("reranker_model", updates.reranker_model);
  const { data } = await client.put(`${PATH}/${id}?${params.toString()}`);
  return data;
}

export async function deleteKB(id: string): Promise<void> {
  await client.delete(`${PATH}/${id}`);
}

// ====== 文档管理 ======

export async function uploadDocument(
  kbId: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<ApiResponse<KBUploadResponse>> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await client.post(`${PATH}/${kbId}/documents`, formData, {
    timeout: KB_UPLOAD_TIMEOUT,
    onUploadProgress: (e) => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    },
  });
  return data;
}

export async function listDocuments(
  kbId: string,
  params: PaginationParams,
): Promise<ApiResponse<PaginatedResponse<KBDocumentListItem>>> {
  const { data } = await client.get(`${PATH}/${kbId}/documents`, {
    params: { page: params.page, page_size: params.page_size },
  });
  return data;
}

export async function getDocument(
  kbId: string,
  docId: string,
): Promise<ApiResponse<KBDocument>> {
  const { data } = await client.get(`${PATH}/${kbId}/documents/${docId}`);
  return data;
}

export async function deleteDocument(kbId: string, docId: string): Promise<void> {
  await client.delete(`${PATH}/${kbId}/documents/${docId}`);
}

export async function cancelDocument(
  kbId: string,
  docId: string,
): Promise<ApiResponse<{ cancelled: boolean }>> {
  const { data } = await client.post(`${PATH}/${kbId}/documents/${docId}/cancel`);
  return data;
}

export async function retryDocument(
  kbId: string,
  docId: string,
): Promise<ApiResponse<{ document_id: string }>> {
  const { data } = await client.post(`${PATH}/${kbId}/documents/${docId}/retry`);
  return data;
}

export async function reprocessDocument(
  kbId: string,
  docId: string,
): Promise<ApiResponse<{ document_id: string }>> {
  const { data } = await client.post(`${PATH}/${kbId}/documents/${docId}/reprocess`);
  return data;
}

// ====== 检索 ======

export async function searchKB(
  kbId: string,
  body: KBSearchRequest,
): Promise<ApiResponse<KBSearchResponse>> {
  const { data } = await client.post(`${PATH}/${kbId}/search`, body, {
    timeout: KB_SEARCH_TIMEOUT,
  });
  return data;
}

// ====== 文档查看 ======

export async function viewDocument(
  kbId: string,
  docId: string,
  page?: number,
): Promise<ApiResponse<KBDocumentView>> {
  const { data } = await client.get(`${PATH}/${kbId}/documents/${docId}/view`, {
    params: page != null ? { page } : undefined,
  });
  return data;
}

/** 获取文档页面元数据（轻量，仅用于页码导航） */
export async function viewDocumentPages(
  kbId: string,
  docId: string,
): Promise<ApiResponse<{ document_id: string; filename: string; file_type: string; total_pages: number; pages: { page_number: number; has_content: boolean }[]; doc_category?: string; doc_category_label?: string }>> {
  const { data } = await client.get(`${PATH}/${kbId}/documents/${docId}/pages`);
  return data;
}

export function getDownloadUrl(kbId: string, docId: string): string {
  return `${client.defaults.baseURL}${PATH}/${kbId}/documents/${docId}/download`;
}

/** 带鉴权的文档下载（Bearer Token） */
export async function downloadDocument(kbId: string, docId: string, filename: string): Promise<void> {
  const response = await client.get(`${PATH}/${kbId}/documents/${docId}/download`, {
    responseType: "blob",
  });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

/** 带鉴权获取内嵌图片 blob */
export async function fetchDocumentImageBlob(
  kbId: string,
  docId: string,
  imageName: string,
): Promise<Blob> {
  const response = await client.get(`${PATH}/${kbId}/documents/${docId}/images/${imageName}`, {
    responseType: "blob",
  });
  return response.data;
}

/** 带鉴权获取源文件 blob（纯图片文档等） */
export async function fetchDocumentDownloadBlob(kbId: string, docId: string): Promise<Blob> {
  const response = await client.get(`${PATH}/${kbId}/documents/${docId}/download`, {
    responseType: "blob",
  });
  return response.data;
}

/** 带鉴权获取 PDF 页面预览 PNG */
export async function fetchPagePreviewBlob(
  kbId: string,
  docId: string,
  pageNum: number,
  scale = 2,
): Promise<{ blob: Blob; pageWidth: number; pageHeight: number }> {
  const response = await client.get(
    `${PATH}/${kbId}/documents/${docId}/pages/${pageNum}/preview`,
    { params: { scale }, responseType: "blob" },
  );
  const pageWidth = Number(response.headers["x-page-width"] || 0);
  const pageHeight = Number(response.headers["x-page-height"] || 0);
  return { blob: response.data, pageWidth, pageHeight };
}

export async function getIndexStatus(kbId: string): Promise<ApiResponse<import("@/types").KBIndexStatus>> {
  const { data } = await client.get(`${PATH}/${kbId}/index-status`);
  return data;
}

export async function reindexKB(kbId: string): Promise<ApiResponse<{ kb_id: string }>> {
  const { data } = await client.post(`${PATH}/${kbId}/reindex`, null, {
    timeout: KB_SEARCH_TIMEOUT,
  });
  return data;
}

export async function getDocumentProgress(
  kbId: string,
  docId: string,
): Promise<ApiResponse<KBProcessProgress | null>> {
  const { data } = await client.get(`${PATH}/${kbId}/documents/${docId}/progress`);
  return data;
}
