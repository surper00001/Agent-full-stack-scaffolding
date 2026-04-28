// 知识库相关类型

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  user_id: string;
  chunk_size: number;
  chunk_overlap: number;
  embedding_model: string;
  reranker_model: string;
  document_count: number;
  total_chunks: number;
  total_size_bytes: number;
  status: string;
  created_at: string;
  updated_at: string;
  indexed_model?: string | null;
  needs_reindex?: boolean;
  server_embedding_model?: string | null;
  server_reranker_model?: string | null;
  models_differ_from_env?: boolean;
}

export interface KnowledgeBaseListItem {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  total_chunks: number;
  total_size_bytes: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface KBDocument {
  id: string;
  knowledge_base_id: string;
  filename: string;
  file_size: number;
  file_type: string;
  page_count: number;
  chunk_count: number;
  status: string;
  error_message: string | null;
  metadata_: {
    doc_category?: string;
    doc_category_label?: string;
    doc_confidence?: number;
    detected_lang?: string;
    headings?: { level: number; title: string; page: number | null }[];
    [key: string]: unknown;
  } | null;
  created_at: string;
  updated_at: string;
}

export interface KBDocumentListItem {
  id: string;
  filename: string;
  file_size: number;
  file_type: string;
  page_count: number;
  chunk_count: number;
  status: string;
  error_message?: string | null;
  created_at: string;
}

export interface KBSearchRequest {
  query: string;
  top_k?: number;
  rerank?: boolean;
  filters?: {
    file_type?: string;
    document_id?: string;
    chunk_type?: "text" | "table" | "image";
  };
}

export interface KBSearchResultItem {
  chunk_id: string;
  document_id: string;
  content: string;
  expanded_content?: string;
  chunk_type: "text" | "table" | "image" | "code";
  page_start: number;
  page_end: number;
  score: number;
  document_filename: string;
  document_file_type: string;
  metadata_: {
    table_html?: string;
    image_path?: string;
    image_url?: string;
    ocr_status?: string;
    ocr_error?: string;
    image_caption?: string;
    image_description?: string;
    parent_context?: string;
    section_title?: string;
    section_path?: string;
    content_summary?: string;
    doc_category?: string;
    bbox?: number[];
  } | null;
  context_before: string | null;
  context_after: string | null;
}

export interface KBSearchResponse {
  query: string;
  results: KBSearchResultItem[];
  total_found: number;
  reranked: boolean;
}

export interface KBUploadResponse {
  document_id: string;
  filename: string;
  file_size: number;
  file_type: string;
  status: string;
  message: string;
}

export interface KBProcessProgress {
  document_id: string;
  stage: "uploaded" | "analyzing" | "parsing" | "chunking" | "embedding" | "indexing" | "ready" | "error";
  stage_label: string;
  percentage: number;
  estimated_seconds: number | null;
  file_size_bytes: number;
  error_message: string | null;
  total_pages?: number;
  parsed_pages?: number;
  text_blocks?: number;
  table_blocks?: number;
  image_blocks?: number;
  total_chunks?: number;
  embedded_chunks?: number;
}

export interface KBIndexStatus {
  indexed_model: string | null;
  current_model: string;
  needs_reindex: boolean;
}

export interface KBPageBlock {
  type: "text" | "table" | "image";
  content: string;
  page: number;
  bbox: number[] | null;
  table_html: string | null;
  image_path: string | null;
  image_url?: string | null;
  ocr_status?: "success" | "empty" | "failed" | "disabled" | null;
  ocr_error?: string | null;
  image_caption?: string | null;
  image_description?: string | null;
  section_title: string | null;
}

export interface KBPageContent {
  page_number: number;
  page_width?: number | null;
  page_height?: number | null;
  text_blocks: KBPageBlock[];
  has_content?: boolean;
}

export interface KBDocumentView {
  document_id: string;
  filename: string;
  file_type: string;
  total_pages: number;
  pages: KBPageContent[];
  doc_category?: string;
  doc_category_label?: string;
}
