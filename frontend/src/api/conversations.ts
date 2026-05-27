import client from "./client";
import type {
  ApiResponse,
  ContextInfoResponse,
  ContextUsageSnapshot,
  Conversation,
  CreateConversationRequest,
  CursorMessagesResponse,
  Message,
  PaginatedResponse,
  PaginationParams,
  StreamEvent,
  TokenUsageStats,
} from "@/types";
import { API_BASE_URL, AUTH_TOKEN_KEY } from "@/lib/constants";

const PATH = "/conversations";

/** 获取对话列表（分页） */
export async function getConversations(
  params?: PaginationParams,
): Promise<ApiResponse<PaginatedResponse<Conversation>>> {
  const { data } = await client.get(PATH, { params });
  return data;
}

/** 获取单个对话（含消息列表） */
export async function getConversation(
  id: string,
): Promise<ApiResponse<Conversation>> {
  const { data } = await client.get(`${PATH}/${id}`);
  return data;
}

/** 创建对话 */
export async function createConversation(
  payload: CreateConversationRequest,
): Promise<ApiResponse<Conversation>> {
  const { data } = await client.post(PATH, payload);
  return data;
}

/** 删除对话 */
export async function deleteConversation(id: string): Promise<void> {
  await client.delete(`${PATH}/${id}`);
}

/** 获取对话消息列表（分页响应） */
export async function getMessages(
  conversationId: string,
  params?: PaginationParams,
): Promise<ApiResponse<PaginatedResponse<Message>>> {
  const { data } = await client.get(`${PATH}/${conversationId}/messages`, { params });
  return data;
}

/** 获取上下文使用统计 */
export async function getContextInfo(
  conversationId: string,
): Promise<ApiResponse<ContextInfoResponse>> {
  const { data } = await client.get(`${PATH}/${conversationId}/context-info`);
  return data;
}

/** 基于游标获取消息分页 */
export async function getMessagesCursor(
  conversationId: string,
  cursor?: string | null,
  limit = 50,
  direction: "backward" | "forward" = "backward",
): Promise<ApiResponse<CursorMessagesResponse>> {
  const { data } = await client.get(`${PATH}/${conversationId}/messages/cursor`, {
    params: { cursor, limit, direction },
  });
  return data;
}

/**
 * 流式发送消息 — 增强版，支持结构化事件。
 *
 * 产出 StreamEvent: delta | tool_call | tool_result | done
 */
export async function* streamMessageV2(
  conversationId: string,
  content: string,
  signal?: AbortSignal,
  mode: "ask" | "agent" | "plan" = "agent",
  planModel?: string | null,
  knowledgeBaseId?: string | null,
  imageIds?: string[] | null,
): AsyncGenerator<StreamEvent, void, unknown> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const response = await fetch(
    `${API_BASE_URL}${PATH}/${conversationId}/send`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        content,
        stream: true,
        mode,
        plan_model: planModel || null,
        knowledge_base_id: knowledgeBaseId || null,
        image_ids: imageIds?.length ? imageIds : null,
      }),
      signal,
    },
  );

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || `请求失败 (${response.status})`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("不支持流式响应");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (!raw || raw === "[DONE]") continue;

      try {
        const payload = JSON.parse(raw);

        if (payload.rag_context) {
          yield { type: "rag_context", data: payload.rag_context };
        } else if (payload.done) {
          yield {
            type: "done",
            data: {
              conversation_id: payload.conversation_id,
              token_usage: payload.token_usage as TokenUsageStats,
              context_usage: payload.context_usage as ContextUsageSnapshot,
            },
          };
        } else if (payload.plan) {
          yield { type: "plan", data: payload.plan };
        } else if (payload.file) {
          yield { type: "file", data: payload.file };
        } else if (payload.tool_calls && payload.status === "tool_call") {
          yield { type: "tool_call", data: payload.tool_calls };
        } else if (payload.tool_results && payload.status === "tool_result") {
          yield { type: "tool_result", data: payload.tool_results };
        } else if (payload.status === "tool_call") {
          yield { type: "tool_call", data: payload.tool_calls || [] };
        } else if (payload.delta) {
          yield { type: "delta", data: payload.delta };
        }
      } catch {
        if (raw && raw !== "[DONE]") {
          yield { type: "delta", data: raw };
        }
      }
    }
  }
}

/**
 * 简单流式 — 向后兼容，仅产出文本块。
 * @deprecated 推荐使用 streamMessageV2 以获取工具调用和上下文信息。
 */
export async function* streamMessage(
  conversationId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<string, void, unknown> {
  for await (const event of streamMessageV2(conversationId, content, signal)) {
    if (event.type === "delta") {
      yield event.data as string;
    }
  }
}

/** 上传聊天图片，返回 image_id 供 send 接口使用 */
export async function uploadChatImage(
  conversationId: string,
  file: File,
): Promise<{ image_id: string; filename: string; preview: string | null }> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await client.post(
    `${PATH}/${conversationId}/images`,
    formData,
    { timeout: 60000 },
  );
  return data.data as { image_id: string; filename: string; preview: string | null };
}
