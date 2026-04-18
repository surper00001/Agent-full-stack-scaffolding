import { useState, useCallback, useRef } from "react";
import type { Conversation } from "@/types";
import * as conversationsApi from "@/api/conversations";

/**
 * 对话列表Hook — 手动触发的分页加载
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
    async (agentId: string, title?: string) => {
      const response = await conversationsApi.createConversation({
        agent_id: agentId,
        title,
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
 * 流式消息Hook
 * 发送消息并以Generator方式逐token接收Agent响应
 */
export function useStreamMessage() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (conversationId: string, content: string): Promise<string> => {
      setIsStreaming(true);
      setStreamContent("");

      let fullContent = "";
      try {
        for await (const chunk of conversationsApi.streamMessage(
          conversationId,
          content,
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
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  return { isStreaming, streamContent, sendMessage, cancelStream };
}
