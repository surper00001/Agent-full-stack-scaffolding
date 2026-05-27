/** 用户列表项（管理员视角） */
export interface UserListItem {
  id: string;
  username: string;
  email: string | null;
  phone: string | null;
  role: "admin" | "user";
  is_active: boolean;
  is_verified: boolean;
  conversation_count: number;
  total_tokens: number;
  created_at: string;
}

/** 用户对话项 */
export interface UserConversationItem {
  id: string;
  title: string;
  agent_type: string;
  message_count: number;
  status: string;
  total_tokens: number;
  knowledge_base_name: string | null;
  created_at: string;
  updated_at: string;
}

/** 用户 Token 消耗明细 */
export interface UserTokenUsageItem {
  conversation_id: string;
  conversation_title: string;
  tokens: number;
  message_count: number;
  created_at: string;
}

/** 每日 Token 消耗 */
export interface DailyTokenItem {
  date: string;
  tokens: number;
}

/** 用户 Token 趋势 */
export interface UserTokenTrend {
  user_id: string;
  username: string;
  total_tokens: number;
  daily: DailyTokenItem[];
  by_conversation: UserTokenUsageItem[];
}

/** 用户详情（管理员视角） */
export interface UserDetail {
  id: string;
  username: string;
  email: string | null;
  phone: string | null;
  role: "admin" | "user";
  is_active: boolean;
  is_verified: boolean;
  conversation_count: number;
  total_tokens: number;
  token_quota: number | null;
  created_at: string;
  updated_at: string;
  recent_conversations: UserConversationItem[];
}
