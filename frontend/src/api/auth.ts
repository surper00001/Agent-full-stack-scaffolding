import client from "./client";
import type { ApiResponse, LoginRequest, TokenResponse, User } from "@/types";

const PATH = "/auth";

/** 登录 */
export async function login(params: LoginRequest): Promise<ApiResponse<TokenResponse>> {
  const { data } = await client.post(`${PATH}/login`, params);
  return data;
}

/** 刷新Token */
export async function refreshToken(
  refresh_token: string,
): Promise<ApiResponse<TokenResponse>> {
  const { data } = await client.post(`${PATH}/refresh`, { refresh_token });
  return data;
}

/** 获取当前用户 */
export async function getCurrentUser(): Promise<ApiResponse<User>> {
  const { data } = await client.get(`${PATH}/me`);
  return data;
}

/** 登出 */
export async function logout(): Promise<void> {
  await client.post(`${PATH}/logout`);
}
