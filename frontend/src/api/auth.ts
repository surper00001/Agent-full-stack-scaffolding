import client from "./client";
import { REFRESH_TOKEN_KEY } from "@/lib/constants";
import type {
  ApiResponse,
  LoginRequest,
  RegisterRequest,
  SendCodeRequest,
  TokenResponse,
  User,
} from "@/types";

const PATH = "/auth";

/** 发送验证码 */
export async function sendCode(params: SendCodeRequest): Promise<ApiResponse<{ target: string; code: string }>> {
  const { data } = await client.post(`${PATH}/send-code`, params);
  return data;
}

/** 注册 */
export async function register(params: RegisterRequest): Promise<ApiResponse<User>> {
  const { data } = await client.post(`${PATH}/register`, params);
  return data;
}

/** 登录 */
export async function login(params: LoginRequest): Promise<ApiResponse<TokenResponse>> {
  const { data } = await client.post(`${PATH}/login`, params);
  return data;
}

/** 刷新 Token */
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

/** 登出 — 撤销 Refresh Token */
export async function logout(refreshToken?: string): Promise<void> {
  const token = refreshToken || localStorage.getItem(REFRESH_TOKEN_KEY);
  if (token) {
    await client.post(`${PATH}/logout`, { refresh_token: token });
  }
}

/** 更新个人信息 */
export async function updateProfile(params: {
  username?: string;
  email?: string;
  phone?: string;
}): Promise<ApiResponse<User>> {
  const { data } = await client.put(`${PATH}/profile`, params);
  return data;
}

/** 修改密码 */
export async function changePassword(params: {
  old_password: string;
  new_password: string;
}): Promise<ApiResponse<null>> {
  const { data } = await client.put(`${PATH}/password`, params);
  return data;
}
