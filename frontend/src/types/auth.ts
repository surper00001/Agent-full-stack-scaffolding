/** 用户信息 */
export interface User {
  id: string;
  tenant_id: string;
  email: string;
  name: string;
  role: "admin" | "member";
  created_at: string;
}

/** 登录请求 */
export interface LoginRequest {
  email: string;
  password: string;
}

/** Token响应 */
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
