import { create } from "zustand";
import type {
  CreateSkillRequest,
  Skill,
  SkillDetail,
  UpdateSkillRequest,
} from "@/types";
import * as skillApi from "@/api/skills";

interface SkillStore {
  skills: Skill[];
  currentSkill: SkillDetail | null;
  isLoading: boolean;
  error: string | null;
  total: number;

  /** 加载 Skill 列表 */
  fetchSkills: (
    page?: number,
    pageSize?: number,
    status?: string,
    category?: string
  ) => Promise<void>;
  /** 加载单个 Skill */
  fetchSkill: (id: string) => Promise<void>;
  /** 创建 Skill */
  createSkill: (payload: CreateSkillRequest) => Promise<SkillDetail>;
  /** 更新 Skill */
  updateSkill: (
    id: string,
    payload: UpdateSkillRequest
  ) => Promise<void>;
  /** 删除 Skill */
  deleteSkill: (id: string) => Promise<void>;
  /** 发布 Skill */
  publishSkill: (id: string) => Promise<void>;
  /** 弃用 Skill */
  deprecateSkill: (id: string) => Promise<void>;
  /** 状态转换 */
  transitionSkill: (
    id: string,
    targetStatus: string,
    reason?: string
  ) => Promise<void>;
}

export const useSkillStore = create<SkillStore>((set, get) => ({
  skills: [],
  currentSkill: null,
  isLoading: false,
  error: null,
  total: 0,

  fetchSkills: async (page = 1, pageSize = 20, status?, category?) => {
    set({ isLoading: true, error: null });
    try {
      const response = await skillApi.getSkills({
        page,
        page_size: pageSize,
        status,
        category,
      });
      set({
        skills: response.data.items,
        total: response.data.total,
        isLoading: false,
      });
    } catch (err) {
      set({
        error: (err as Error).message,
        isLoading: false,
      });
    }
  },

  fetchSkill: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await skillApi.getSkill(id);
      set({ currentSkill: response.data, isLoading: false });
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false });
    }
  },

  createSkill: async (payload: CreateSkillRequest) => {
    const response = await skillApi.createSkill(payload);
    set({ skills: [...get().skills, response.data] });
    return response.data;
  },

  updateSkill: async (id: string, payload: UpdateSkillRequest) => {
    const response = await skillApi.updateSkill(id, payload);
    set({
      skills: get().skills.map((s) =>
        s.id === id ? response.data : s
      ),
      currentSkill:
        get().currentSkill?.id === id
          ? response.data
          : get().currentSkill,
    });
  },

  deleteSkill: async (id: string) => {
    await skillApi.deleteSkill(id);
    set({
      skills: get().skills.filter((s) => s.id !== id),
      currentSkill:
        get().currentSkill?.id === id ? null : get().currentSkill,
    });
  },

  publishSkill: async (id: string) => {
    const response = await skillApi.publishSkill(id);
    set({
      skills: get().skills.map((s) =>
        s.id === id ? response.data : s
      ),
      currentSkill:
        get().currentSkill?.id === id
          ? response.data
          : get().currentSkill,
    });
  },

  deprecateSkill: async (id: string) => {
    const response = await skillApi.deprecateSkill(id);
    set({
      skills: get().skills.map((s) =>
        s.id === id ? response.data : s
      ),
      currentSkill:
        get().currentSkill?.id === id
          ? response.data
          : get().currentSkill,
    });
  },

  transitionSkill: async (id: string, targetStatus: string, reason?: string) => {
    const response = await skillApi.transitionSkill(id, targetStatus, reason);
    set({
      skills: get().skills.map((s) =>
        s.id === id ? response.data : s
      ),
      currentSkill:
        get().currentSkill?.id === id
          ? response.data
          : get().currentSkill,
    });
  },
}));
