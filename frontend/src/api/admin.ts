import client from "./client";
import type { ApiResponse } from "@/types";

export interface AdminStats {
  total_users: number;
  total_conversations: number;
  total_messages: number;
  total_tokens: number;
  active_users_today: number;
  tokens_today: number;
}

/** 获取管理仪表盘统计数据 */
export async function getAdminStats(): Promise<ApiResponse<AdminStats>> {
  const { data } = await client.get("/admin/stats");
  return data;
}
