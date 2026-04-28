/** 用户信息 — 对齐后端 UserResponse */
export interface User {
  id: string;
  username: string;
  phone: string | null;
  email: string | null;
  is_active: boolean;
  is_verified: boolean;
  role: "admin" | "user";
  created_at: string;
  updated_at: string;
}

/** 登录请求 — 后端使用 account 字段（支持用户名/手机号/邮箱），code 为图形验证码 */
export interface LoginRequest {
  account: string;
  password: string;
  code?: string;
}

/** 注册请求 */
export interface RegisterRequest {
  username: string;
  phone?: string;
  email?: string;
  password: string;
  code: string;
}

/** 发送验证码请求 */
export interface SendCodeRequest {
  target: string;
  method: "email" | "sms";
}

/** Token 响应 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** 认证状态 */
export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}
