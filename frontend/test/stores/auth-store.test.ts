/**
 * AuthStore 测试 — 覆盖登录/登出/会话恢复核心流程。
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { AUTH_TOKEN_KEY, REFRESH_TOKEN_KEY } from "@/lib/constants";

// 模拟 API 模块
vi.mock("@/api/auth", () => ({
  login: vi.fn(),
  getCurrentUser: vi.fn(),
  logout: vi.fn(),
}));

import * as authApi from "@/api/auth";

const mockUser = {
  id: "user-1",
  username: "admin",
  phone: null,
  email: "admin@example.com",
  is_active: true,
  is_verified: true,
  role: "admin" as const,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

const mockTokenResponse = {
  access_token: "mock-access",
  refresh_token: "mock-refresh",
  token_type: "bearer",
  expires_in: 1800,
};

function resetStore() {
  useAuthStore.setState({
    user: null,
    isAuthenticated: false,
    isAdmin: false,
    isLoading: true,
  });
}

describe("AuthStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    resetStore();
  });

  describe("initAuth", () => {
    it("token 不存在时设置 isLoading=false", async () => {
      await useAuthStore.getState().initAuth();

      const state = useAuthStore.getState();
      expect(state.isLoading).toBe(false);
      expect(state.isAuthenticated).toBe(false);
      expect(state.user).toBeNull();
    });

    it("token 存在且有效时恢复用户信息", async () => {
      localStorage.setItem(AUTH_TOKEN_KEY, "valid-token");
      vi.mocked(authApi.getCurrentUser).mockResolvedValue({
        success: true,
        code: 0,
        message: "",
        data: mockUser,
      });

      await useAuthStore.getState().initAuth();

      const state = useAuthStore.getState();
      expect(state.isLoading).toBe(false);
      expect(state.isAuthenticated).toBe(true);
      expect(state.user).toEqual(mockUser);
      expect(state.isAdmin).toBe(true);
    });

    it("token 存在但过期时清除状态", async () => {
      localStorage.setItem(AUTH_TOKEN_KEY, "expired-token");
      vi.mocked(authApi.getCurrentUser).mockRejectedValue(new Error("Unauthorized"));

      await useAuthStore.getState().initAuth();

      const state = useAuthStore.getState();
      expect(state.isLoading).toBe(false);
      expect(state.isAuthenticated).toBe(false);
      expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    });
  });

  describe("login", () => {
    it("登录成功存储 token 并设置用户", async () => {
      vi.mocked(authApi.login).mockResolvedValue({
        success: true,
        code: 0,
        message: "登录成功",
        data: mockTokenResponse,
      });
      vi.mocked(authApi.getCurrentUser).mockResolvedValue({
        success: true,
        code: 0,
        message: "",
        data: mockUser,
      });

      await useAuthStore.getState().login({
        account: "admin",
        password: "pass",
      });

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(true);
      expect(state.user).toEqual(mockUser);
      expect(state.isAdmin).toBe(true);
      expect(state.isLoading).toBe(false);
      expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe("mock-access");
      expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe("mock-refresh");
    });

    it("登录失败抛出异常不修改状态", async () => {
      vi.mocked(authApi.login).mockRejectedValue(new Error("Invalid credentials"));

      await expect(
        useAuthStore.getState().login({ account: "admin", password: "wrong" }),
      ).rejects.toThrow();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.user).toBeNull();
    });
  });

  describe("logout", () => {
    it("登出清除 token 和用户状态", async () => {
      // 先设置已登录状态
      useAuthStore.setState({
        user: mockUser,
        isAuthenticated: true,
        isAdmin: true,
        isLoading: false,
      });
      localStorage.setItem(AUTH_TOKEN_KEY, "some-token");
      localStorage.setItem(REFRESH_TOKEN_KEY, "some-refresh");
      vi.mocked(authApi.logout).mockResolvedValue(undefined);

      await useAuthStore.getState().logout();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.user).toBeNull();
      expect(state.isAdmin).toBe(false);
      expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
      expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
    });

    it("登出 API 失败仍清除本地状态", async () => {
      useAuthStore.setState({
        user: mockUser,
        isAuthenticated: true,
        isAdmin: true,
        isLoading: false,
      });
      localStorage.setItem(AUTH_TOKEN_KEY, "some-token");
      vi.mocked(authApi.logout).mockRejectedValue(new Error("Network error"));

      await useAuthStore.getState().logout();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    });
  });

  describe("isAdmin 派生状态", () => {
    it("普通用户 isAdmin=false", () => {
      useAuthStore.setState({
        user: { ...mockUser, role: "user" },
        isAuthenticated: true,
        isAdmin: false,
        isLoading: false,
      });

      expect(useAuthStore.getState().isAdmin).toBe(false);
    });

    it("管理员 isAdmin=true", () => {
      useAuthStore.setState({
        user: { ...mockUser, role: "admin" },
        isAuthenticated: true,
        isAdmin: true,
        isLoading: false,
      });

      expect(useAuthStore.getState().isAdmin).toBe(true);
    });
  });
});
