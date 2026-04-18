/** 消息角色 */
export type MessageRole = "user" | "assistant" | "system" | "tool";

/** 对话消息 */
export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  tool_calls?: ToolCall[];
  created_at: string;
}

/** 工具调用记录 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
}

/** 对话实体 */
export interface Conversation {
  id: string;
  tenant_id: string;
  agent_id: string;
  title: string;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

/** 创建对话请求 */
export interface CreateConversationRequest {
  agent_id: string;
  title?: string;
}

/** 发送消息请求 */
export interface SendMessageRequest {
  content: string;
  stream?: boolean;
}
