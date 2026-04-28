import { create } from "zustand";
import type { Tenant, TokenUsage } from "@/types";
import * as tenantApi from "@/api/tenant";

interface TenantStore {
  tenant: Tenant | null;
  usage: TokenUsage | null;
  isLoading: boolean;
  error: string | null;

  fetchTenant: () => Promise<void>;
  fetchUsage: (days?: number) => Promise<void>;
}

export const useTenantStore = create<TenantStore>((set) => ({
  tenant: null,
  usage: null,
  isLoading: false,
  error: null,

  fetchTenant: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await tenantApi.getTenant();
      set({ tenant: res.data, isLoading: false });
    } catch (err) {
      set({ error: (err as Error).message || "获取租户信息失败", isLoading: false });
    }
  },

  fetchUsage: async (days = 30) => {
    set({ isLoading: true, error: null });
    try {
      const res = await tenantApi.getTokenUsage(days);
      set({ usage: res.data, isLoading: false });
    } catch (err) {
      set({ error: (err as Error).message || "获取用量数据失败", isLoading: false });
    }
  },
}));
