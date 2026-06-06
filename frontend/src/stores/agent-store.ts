import { create } from "zustand";
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "@/types";
import * as agentApi from "@/api/agents";

interface AgentStore {
  agents: Agent[];
  currentAgent: Agent | null;
  isLoading: boolean;
  error: string | null;
  total: number;

  /** 加载Agent列表 */
  fetchAgents: (page?: number, pageSize?: number) => Promise<void>;
  /** 加载单个Agent */
  fetchAgent: (id: string) => Promise<void>;
  /** 创建Agent */
  createAgent: (payload: CreateAgentRequest) => Promise<Agent>;
  /** 更新Agent */
  updateAgent: (id: string, payload: UpdateAgentRequest) => Promise<void>;
  /** 删除Agent */
  deleteAgent: (id: string) => Promise<void>;
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  agents: [],
  currentAgent: null,
  isLoading: false,
  error: null,
  total: 0,

  fetchAgents: async (page = 1, pageSize = 20) => {
    set({ isLoading: true, error: null });
    try {
      const response = await agentApi.getAgents({ page, page_size: pageSize });
      set({
        agents: response.data.items,
        total: response.data.total,
        isLoading: false,
      });
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false });
    }
  },

  fetchAgent: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await agentApi.getAgent(id);
      set({ currentAgent: response.data, isLoading: false });
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false });
    }
  },

  createAgent: async (payload: CreateAgentRequest) => {
    const response = await agentApi.createAgent(payload);
    set({ agents: [...get().agents, response.data] });
    return response.data;
  },

  updateAgent: async (id: string, payload: UpdateAgentRequest) => {
    const response = await agentApi.updateAgent(id, payload);
    set({
      agents: get().agents.map((a) => (a.id === id ? response.data : a)),
      currentAgent:
        get().currentAgent?.id === id ? response.data : get().currentAgent,
    });
  },

  deleteAgent: async (id: string) => {
    // 乐观删除 — 先更新 UI，失败时回滚
    const prev = { agents: get().agents, currentAgent: get().currentAgent };
    set({
      agents: get().agents.filter((a) => a.id !== id),
      currentAgent: prev.currentAgent?.id === id ? null : prev.currentAgent,
    });
    try {
      await agentApi.deleteAgent(id);
    } catch {
      set({ agents: prev.agents, currentAgent: prev.currentAgent });
    }
  },
}));
