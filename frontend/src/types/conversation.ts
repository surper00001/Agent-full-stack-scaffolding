/** 消息角色 */
export type MessageRole = "user" | "assistant" | "system" | "tool";

/** 对话消息 */
export interface Message {
  id: string;
  conversation_id?: string;
  role: MessageRole;
  content: string;
  token_count?: number | null;
  metadata_?: Record<string, unknown> | null;
  tool_calls?: ToolCall[];
  created_at: string;
}

/** 工具调用记录 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  status?: "running" | "completed" | "error";
}

/** 对话实体 */
export interface Conversation {
  id: string;
  tenant_id?: string;
  agent_type: string;
  title: string;
  message_count: number;
  status: string;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  user_id?: string | null;
  username?: string | null;
  /** 详情接口不内嵌消息，需单独调用 messages/cursor */
  messages?: Message[];
  created_at: string;
  updated_at: string;
}

/** 创建对话请求 */
export interface CreateConversationRequest {
  title?: string;
  agent_type?: string;
  knowledge_base_id?: string | null;
}

/** 对话模式 */
export type ChatMode = "ask" | "agent" | "plan";

/** 发送消息请求 */
export interface SendMessageRequest {
  content: string;
  stream?: boolean;
  mode?: ChatMode;
  plan_model?: string | null;
  knowledge_base_id?: string | null;
  image_ids?: string[] | null;
}

/** 上下文使用统计 */
export interface ContextInfoResponse {
  total_messages: number;
  total_tokens: number;
  max_context: number;
  usage_ratio: number;
  model: string;
}

/** 游标分页消息响应 */
export interface CursorMessagesResponse {
  items: Message[];
  next_cursor: string | null;
  limit: number;
}

/** 流式事件类型 */
export type StreamEventType = "delta" | "tool_call" | "tool_result" | "plan" | "file" | "rag_context" | "done" | "error" | "thinking";

/** 流式事件 */
export interface StreamEvent {
  type: StreamEventType;
  data: unknown;
}

/** 上下文使用快照（来自 SSE done 事件） */
export interface ContextUsageSnapshot {
  used_tokens: number;
  max_tokens: number;
  strategy: string;
  compressed_ratio: number;
  has_summary: boolean;
}

/** Token 用量统计 */
export interface TokenUsageStats {
  call_count: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_cost: number;
}

/** KB 检索引用 */
export interface KBCitation {
  content: string;
  source: string;
  page: number;
  score: number;
  chunk_id: string;
  chunk_type: "text" | "table" | "image";
  section_title?: string;
  document_id?: string;
  /** 图片块专用字段 */
  image_url?: string;
  image_description?: string;
  image_caption?: string;
  ocr_status?: string;
}

/** 流式事件增强：所有事件都带 _timing */
export interface StreamTiming {
  elapsed_ms: number;
  ttft_ms?: number | null;
  tokens_per_second?: number;
  total_elapsed_ms?: number;
}

/** 思考过程事件 */
export interface ThinkingEvent {
  thinking: string;
  _timing?: StreamTiming;
}

/** Agent 时间线条目 */
export interface TimelineEntry {
  id: string;
  type: "thinking" | "tool_call" | "tool_result" | "text";
  content: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: unknown;
  status?: "running" | "completed" | "error";
  elapsed_ms: number;
  duration_ms?: number;
}

/** KB 搜索结果（来自 search_knowledge_base 工具） */
export interface KBSearchToolResult {
  query: string;
  total_found: number;
  returned: number;
  results: KBCitation[];
}
