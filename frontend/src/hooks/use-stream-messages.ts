/**
 * useStreamMessages — SSE 流式消息 Hook。
 *
 * 从 ChatDetailPage 提取流式逻辑，减少父组件复杂度。
 * 管理 SSE 连接、消息累积、中断/重试、滚动管理。
 */
import { useState, useRef, useCallback } from "react";
import { API_BASE_URL, AUTH_TOKEN_KEY } from "@/lib/constants";
import type { KBCitation } from "@/components/kb/citation-cards";

interface StreamOptions {
  conversationId: string;
  activeKbId?: string | null;
  onChunk?: (content: string) => void;
  onCitations?: (citations: KBCitation[]) => void;
  onError?: (error: string) => void;
}

interface StreamState {
  isStreaming: boolean;
  streamContent: string;
  citations: KBCitation[];
}

export function useStreamMessages() {
  const [state, setState] = useState<StreamState>({
    isStreaming: false,
    streamContent: "",
    citations: [],
  });
  const abortRef = useRef<AbortController | null>(null);

  const startStream = useCallback(async (options: StreamOptions) => {
    const { conversationId, activeKbId, onChunk, onCitations, onError } = options;

    // 取消之前的流
    abortRef.current?.abort();

    const controller = new AbortController();
    abortRef.current = controller;

    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) {
      onError?.("未登录");
      return;
    }

    setState((s) => ({ ...s, isStreaming: true, streamContent: "", citations: [] }));

    try {
      const url = new URL(`${API_BASE_URL}/conversations/${conversationId}/send`);
      if (activeKbId) {
        url.searchParams.set("knowledge_base_id", activeKbId);
      }

      const response = await fetch(url.toString(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: "", stream: true }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("无法获取响应流");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 解析 SSE 事件
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.type === "content" || data.content) {
                const content = data.content || "";
                setState((s) => ({ ...s, streamContent: s.streamContent + content }));
                onChunk?.(content);
              } else if (data.type === "citations" || data.citations) {
                const cits = data.citations || [];
                setState((s) => ({ ...s, citations: cits }));
                onCitations?.(cits);
              } else if (data.type === "error") {
                onError?.(data.message || "流错误");
              } else if (data.type === "done" || data.done) {
                // 流结束
              }
            } catch {
              // 非 JSON 行，忽略
            }
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return; // 用户主动取消
      }
      const msg = err instanceof Error ? err.message : "请求失败";
      onError?.(msg);
    } finally {
      setState((s) => ({ ...s, isStreaming: false }));
    }
  }, []);

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const resetStream = useCallback(() => {
    setState({ isStreaming: false, streamContent: "", citations: [] });
  }, []);

  return {
    ...state,
    startStream,
    stopStream,
    resetStream,
  };
}
