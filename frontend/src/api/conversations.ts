import client from "./client";
import type {
  ApiResponse,
  Conversation,
  CreateConversationRequest,
  Message,
  PaginatedResponse,
  PaginationParams,
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

/** 获取单个对话 */
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

/**
 * 流式发送消息 — 使用fetch原生ReadableStream
 * 支持Agent实时响应推流，逐token返回
 */
export async function* streamMessage(
  conversationId: string,
  content: string,
): AsyncGenerator<string, void, unknown> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const response = await fetch(
    `${API_BASE_URL}${PATH}/${conversationId}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ content, stream: true }),
    },
  );

  if (!response.ok) {
    throw new Error(`消息发送失败: ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const chunk = line.slice(6).trim();
        if (chunk === "[DONE]") return;
        yield chunk;
      }
    }
  }
}

/** 获取对话消息列表 */
export async function getMessages(
  conversationId: string,
): Promise<ApiResponse<Message[]>> {
  const { data } = await client.get(`${PATH}/${conversationId}/messages`);
  return data;
}
