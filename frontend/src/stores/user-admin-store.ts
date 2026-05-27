import { create } from "zustand";
import type { UserListItem, UserDetail, DailyTokenItem, UserConversationItem, UserTokenTrend } from "@/types";
import * as usersApi from "@/api/users";

interface UserAdminStore {
  // 用户列表
  users: UserListItem[];
  total: number;
  loading: boolean;
  error: string | null;

  // 用户详情
  currentUser: UserDetail | null;
  detailLoading: boolean;

  // 用户 Token 趋势
  tokenTrend: DailyTokenItem[] | null;
  tokenUsage: UserTokenTrend | null;
  trendLoading: boolean;
  trendDays: number;

  // 用户对话列表
  userConversations: UserConversationItem[];
  userConvTotal: number;
  userConvPage: number;
  convLoading: boolean;

  // Actions
  fetchUsers: (page?: number, pageSize?: number, search?: string) => Promise<void>;
  fetchUserDetail: (userId: string) => Promise<void>;
  fetchUserConversations: (userId: string, page?: number, pageSize?: number) => Promise<void>;
  fetchUserTokenUsage: (userId: string) => Promise<void>;
  fetchUserTokenTrend: (userId: string, days?: number) => Promise<void>;
  deleteUser: (userId: string) => Promise<void>;
  deleteUserConversations: (userId: string) => Promise<void>;
  setTokenQuota: (userId: string, quota: number) => Promise<void>;
  updateUserRole: (userId: string, role: "admin" | "user") => Promise<void>;
  toggleUserActive: (userId: string) => Promise<void>;
  reset: () => void;
}

export const useUserAdminStore = create<UserAdminStore>((set, get) => ({
  users: [],
  total: 0,
  loading: false,
  error: null,

  currentUser: null,
  detailLoading: false,

  tokenTrend: null,
  tokenUsage: null,
  trendLoading: false,
  trendDays: 7,

  userConversations: [],
  userConvTotal: 0,
  userConvPage: 1,
  convLoading: false,

  fetchUsers: async (page = 1, pageSize = 20, search) => {
    set({ loading: true, error: null });
    try {
      const res = await usersApi.getUsers({ page, page_size: pageSize, search });
      set({
        users: res.data.items,
        total: res.data.total,
        loading: false,
      });
    } catch (err) {
      set({ error: (err as Error).message || "获取用户列表失败", loading: false });
    }
  },

  fetchUserDetail: async (userId) => {
    set({ detailLoading: true });
    try {
      const res = await usersApi.getUserDetail(userId);
      set({ currentUser: res.data, detailLoading: false });
    } catch (err) {
      set({ error: (err as Error).message || "获取用户详情失败", detailLoading: false });
    }
  },

  fetchUserConversations: async (userId, page = 1, pageSize = 20) => {
    set({ convLoading: true });
    try {
      const res = await usersApi.getUserConversations(userId, { page, page_size: pageSize });
      set({
        userConversations: res.data.items,
        userConvTotal: res.data.total,
        userConvPage: page,
        convLoading: false,
      });
    } catch {
      set({ convLoading: false });
    }
  },

  fetchUserTokenUsage: async (userId) => {
    set({ trendLoading: true });
    try {
      const res = await usersApi.getUserTokenUsage(userId);
      set({ tokenUsage: res.data, trendLoading: false });
    } catch {
      set({ trendLoading: false });
    }
  },

  fetchUserTokenTrend: async (userId, days = 7) => {
    set({ trendLoading: true, trendDays: days });
    try {
      const res = await usersApi.getUserTokenTrend(userId, days);
      set({ tokenTrend: res.data, trendLoading: false });
    } catch {
      set({ trendLoading: false });
    }
  },

  deleteUser: async (userId) => {
    await usersApi.deleteUser(userId);
    set((s) => ({
      users: s.users.filter((u) => u.id !== userId),
      total: s.total - 1,
    }));
  },

  deleteUserConversations: async (userId) => {
    await usersApi.deleteUserConversations(userId);
    set({ userConversations: [], userConvTotal: 0 });
    // 刷新用户详情
    get().fetchUserDetail(userId);
  },

  setTokenQuota: async (userId, quota) => {
    await usersApi.setTokenQuota(userId, quota);
    // 刷新详情
    get().fetchUserDetail(userId);
  },

  updateUserRole: async (userId, role) => {
    await usersApi.updateUserRole(userId, role);
    // 刷新列表和详情
    get().fetchUserDetail(userId);
    get().fetchUsers();
  },

  toggleUserActive: async (userId) => {
    await usersApi.toggleUserActive(userId);
    // 刷新列表和详情
    get().fetchUserDetail(userId);
    get().fetchUsers();
  },

  reset: () =>
    set({
      currentUser: null,
      tokenTrend: null,
      tokenUsage: null,
      userConversations: [],
      userConvTotal: 0,
      userConvPage: 1,
    }),
}));
