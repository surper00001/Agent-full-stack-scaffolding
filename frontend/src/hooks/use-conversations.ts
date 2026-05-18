import { useState, useCallback } from "react";
import type { Conversation } from "@/types";
import * as conversationsApi from "@/api/conversations";
import { useConversationStore } from "@/stores/conversation-store";

/**
 * 对话列表 Hook — 委托到共享 Zustand store，保证侧边栏与聊天页状态一致。
 */
export function useConversations() {
  const {
    conversations,
    total,
    loading,
    fetchConversations,
    createConversation,
    deleteConversation,
  } = useConversationStore();

  return {
    conversations,
    total,
    isLoading: loading,
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
