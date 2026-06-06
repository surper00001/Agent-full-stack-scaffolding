import { create } from "zustand";
import type { Conversation } from "@/types";
import * as conversationsApi from "@/api/conversations";

interface ConversationStore {
  conversations: Conversation[];
  total: number;
  loading: boolean;

  fetchConversations: (page?: number, pageSize?: number) => Promise<void>;
  createConversation: (
    title?: string,
    agentType?: string,
    knowledgeBaseId?: string | null,
  ) => Promise<Conversation>;
  deleteConversation: (id: string) => Promise<void>;
  /** 发送消息后刷新列表（更新 message_count 和排序） */
  refreshConversations: () => Promise<void>;
}

export const useConversationStore = create<ConversationStore>((set, get) => ({
  conversations: [],
  total: 0,
  loading: false,

  fetchConversations: async (page = 1, pageSize = 50) => {
    set({ loading: true });
    try {
      const response = await conversationsApi.getConversations({
        page,
        page_size: pageSize,
      });
      set({
        conversations: response.data.items,
        total: response.data.total,
        loading: false,
      });
    } catch {
      set({ loading: false });
    }
  },

  createConversation: async (title, agentType = "general", knowledgeBaseId) => {
    const response = await conversationsApi.createConversation({
      title: title || "新对话",
      agent_type: agentType,
      knowledge_base_id: knowledgeBaseId || undefined,
    });
    set((s) => ({ conversations: [response.data, ...s.conversations] }));
    return response.data;
  },

  deleteConversation: async (id) => {
    // 乐观删除 — 先更新 UI，失败时回滚
    const prev = get().conversations;
    set((s) => ({ conversations: s.conversations.filter((c) => c.id !== id) }));
    try {
      await conversationsApi.deleteConversation(id);
    } catch {
      set({ conversations: prev });
    }
  },

  refreshConversations: async () => {
    try {
      const response = await conversationsApi.getConversations({
        page: 1,
        page_size: 50,
      });
      set({
        conversations: response.data.items,
        total: response.data.total,
      });
    } catch {
      // silent — keep existing list on error
    }
  },
}));
