import client from "./client";
import type {
  ApiResponse,
  PaginatedResponse,
  UserListItem,
  UserDetail,
  UserConversationItem,
  UserTokenTrend,
  DailyTokenItem,
} from "@/types";

const PATH = "/users";

/** 获取用户列表 */
export async function getUsers(params?: {
  page?: number;
  page_size?: number;
  search?: string;
}): Promise<ApiResponse<PaginatedResponse<UserListItem>>> {
  const { data } = await client.get(PATH, { params });
  return data;
}

/** 获取用户详情 */
export async function getUserDetail(
  userId: string,
): Promise<ApiResponse<UserDetail>> {
  const { data } = await client.get(`${PATH}/${userId}`);
  return data;
}

/** 获取用户对话列表 */
export async function getUserConversations(
  userId: string,
  params?: { page?: number; page_size?: number },
): Promise<ApiResponse<PaginatedResponse<UserConversationItem>>> {
  const { data } = await client.get(`${PATH}/${userId}/conversations`, { params });
  return data;
}

/** 获取用户 Token 消耗明细 */
export async function getUserTokenUsage(
  userId: string,
): Promise<ApiResponse<UserTokenTrend>> {
  const { data } = await client.get(`${PATH}/${userId}/token-usage`);
  return data;
}

/** 获取用户 Token 使用趋势 */
export async function getUserTokenTrend(
  userId: string,
  days = 7,
): Promise<ApiResponse<DailyTokenItem[]>> {
  const { data } = await client.get(`${PATH}/${userId}/token-trend`, {
    params: { days },
  });
  return data;
}

/** 删除用户 */
export async function deleteUser(userId: string): Promise<void> {
  await client.delete(`${PATH}/${userId}`);
}

/** 清空用户对话 */
export async function deleteUserConversations(userId: string): Promise<void> {
  await client.delete(`${PATH}/${userId}/conversations`);
}

/** 设置用户 Token 配额 */
export async function setTokenQuota(
  userId: string,
  token_quota: number,
): Promise<ApiResponse<{ user_id: string; token_quota: number }>> {
  const { data } = await client.put(`${PATH}/${userId}/token-quota`, {
    token_quota,
  });
  return data;
}

/** 更新用户角色 */
export async function updateUserRole(
  userId: string,
  role: "admin" | "user",
): Promise<ApiResponse<{ user_id: string; role: string }>> {
  const { data } = await client.put(`${PATH}/${userId}/role`, { role });
  return data;
}

/** 启用/禁用用户 */
export async function toggleUserActive(
  userId: string,
): Promise<ApiResponse<{ user_id: string; is_active: boolean }>> {
  const { data } = await client.post(`${PATH}/${userId}/toggle-active`);
  return data;
}
