import { create } from "zustand";
import type { User, LoginRequest } from "@/types";
import * as authApi from "@/api/auth";
import { AUTH_TOKEN_KEY, REFRESH_TOKEN_KEY } from "@/lib/constants";

interface AuthStore {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isAdmin: boolean;

  /** 登录 — 成功后存储token并获取用户信息 */
  login: (params: LoginRequest) => Promise<void>;
  /** 登出 — 清除token和用户状态 */
  logout: () => Promise<void>;
  /** 初始化 — 从localStorage恢复token并验证有效性 */
  initAuth: () => Promise<void>;
}

function deriveState(user: User | null) {
  return {
    user,
    isAuthenticated: user !== null,
    isAdmin: user?.role === "admin",
    isLoading: false,
  };
}

/**
 * 认证状态管理
 * 全局唯一的认证Store，管理登录/登出/会话恢复
 */
export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  isAuthenticated: false,
  isAdmin: false,
  isLoading: true,

  login: async (params: LoginRequest) => {
    const response = await authApi.login(params);
    const { access_token, refresh_token } = response.data;

    localStorage.setItem(AUTH_TOKEN_KEY, access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token);

    const userResponse = await authApi.getCurrentUser();
    set(deriveState(userResponse.data));
  },

  logout: async () => {
    try {
      const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
      if (refreshToken) {
        await authApi.logout(refreshToken);
      }
    } finally {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      set({ user: null, isAuthenticated: false, isAdmin: false, isLoading: false });
    }
  },

  initAuth: async () => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      const response = await authApi.getCurrentUser();
      set(deriveState(response.data));
    } catch {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      set({ isLoading: false });
    }
  },
}));
