import { useState, useCallback } from "react";
import type { Conversation } from "@/types";
import * as conversationsApi from "@/api/conversations";

/**
 * 对话列表 Hook — 手动触发的分页加载
 */
export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [total, setTotal] = useState(0);

  const fetchConversations = useCallback(
    async (page = 1, pageSize = 20) => {
      setIsLoading(true);
      try {
        const response = await conversationsApi.getConversations({
          page,
          page_size: pageSize,
        });
        setConversations(response.data.items);
        setTotal(response.data.total);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const createConversation = useCallback(
    async (title?: string, agentType = "general", knowledgeBaseId?: string | null) => {
      const response = await conversationsApi.createConversation({
        title: title || "新对话",
        agent_type: agentType,
        knowledge_base_id: knowledgeBaseId || undefined,
      });
      setConversations((prev) => [response.data, ...prev]);
      return response.data;
    },
    [],
  );

  const deleteConversation = useCallback(async (id: string) => {
    await conversationsApi.deleteConversation(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
  }, []);

  return {
    conversations,
    total,
    isLoading,
    fetchConversations,
    createConversation,
    deleteConversation,
  };
}

/**
 * 流式消息 Hook（简化版，供外部组合使用）
 */
export function useStreamMessage() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");

  const sendMessage = useCallback(
    async (
      conversationId: string,
      content: string,
      signal?: AbortSignal,
    ): Promise<string> => {
      setIsStreaming(true);
      setStreamContent("");

      let fullContent = "";
      try {
        for await (const chunk of conversationsApi.streamMessage(
          conversationId,
          content,
          signal,
        )) {
          fullContent += chunk;
          setStreamContent(fullContent);
        }
      } finally {
        setIsStreaming(false);
      }
      return fullContent;
    },
    [],
  );

  const cancelStream = useCallback(() => {
    setIsStreaming(false);
    setStreamContent("");
  }, []);

  return { isStreaming, streamContent, sendMessage, cancelStream };
}
