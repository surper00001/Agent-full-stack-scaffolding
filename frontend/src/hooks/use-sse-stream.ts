import { useState, useRef, useCallback } from "react";
import type { StreamTiming, ToolCall } from "@/types";

interface SSEMessageHandlers {
  onDelta?: (text: string, timing?: StreamTiming) => void;
  onThinking?: (thinking: string, timing?: StreamTiming) => void;
  onToolCall?: (calls: ToolCall[], timing?: StreamTiming) => void;
  onToolResult?: (results: ToolCall[], timing?: StreamTiming) => void;
  onPlan?: (steps: unknown[], summary: string, timing?: StreamTiming) => void;
  onFile?: (file: Record<string, unknown>) => void;
  onRagContext?: (ctx: Record<string, unknown>) => void;
  onDone?: (data: Record<string, unknown>) => void;
  onError?: (error: string) => void;
}

interface UseSSEStreamOptions {
  handlers: SSEMessageHandlers;
  maxRetries?: number;
  retryDelayMs?: number;
}

export function useSSEStream(options: UseSSEStreamOptions) {
  const { handlers, maxRetries = 3, retryDelayMs = 2000 } = options;
  const [connectionStatus, setConnectionStatus] = useState<"idle" | "connected" | "reconnecting" | "disconnected" | "error">("idle");
  const [retryCount, setRetryCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const retryTimeoutRef = useRef<number | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const connect = useCallback(async (url: string, body: unknown) => {
    setConnectionStatus("connected");
    setRetryCount(0);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        if (response.status === 429) {
          handlersRef.current.onError?.("请求过于频繁，请稍后重试 (429)");
        } else {
          handlersRef.current.onError?.(`请求失败: ${response.status} ${errorText}`);
        }
        setConnectionStatus("error");
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        handlersRef.current.onError?.("无法读取响应流");
        setConnectionStatus("error");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            if (dataStr === "[DONE]") {
              setConnectionStatus("idle");
              return;
            }
            try {
              const event = JSON.parse(dataStr);
              const timing = event._timing as StreamTiming | undefined;

              if (event.delta && handlersRef.current.onDelta) {
                handlersRef.current.onDelta(event.delta, timing);
              }
              if (event.thinking && handlersRef.current.onThinking) {
                handlersRef.current.onThinking(event.thinking, timing);
              }
              if (event.tool_calls && handlersRef.current.onToolCall) {
                handlersRef.current.onToolCall(event.tool_calls, timing);
              }
              if (event.tool_results && handlersRef.current.onToolResult) {
                handlersRef.current.onToolResult(event.tool_results, timing);
              }
              if (event.plan && handlersRef.current.onPlan) {
                handlersRef.current.onPlan(event.plan.steps, event.plan.summary, timing);
              }
              if (event.file && handlersRef.current.onFile) {
                handlersRef.current.onFile(event.file);
              }
              if (event.rag_context && handlersRef.current.onRagContext) {
                handlersRef.current.onRagContext(event.rag_context);
              }
              if (event.done && handlersRef.current.onDone) {
                handlersRef.current.onDone(event);
              }
              if (event.error && handlersRef.current.onError) {
                handlersRef.current.onError(event.error);
              }
            } catch {
              // Skip unparseable lines
            }
          }
        }
      }
      setConnectionStatus("idle");
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        setConnectionStatus("idle");
        return;
      }

      // Auto-retry on network errors
      const currentRetry = retryCount;
      if (currentRetry < maxRetries) {
        setConnectionStatus("reconnecting");
        setRetryCount(currentRetry + 1);
        retryTimeoutRef.current = window.setTimeout(() => {
          connect(url, body);
        }, retryDelayMs * (currentRetry + 1));
      } else {
        setConnectionStatus("error");
        handlersRef.current.onError?.(
          `连接失败，已重试 ${maxRetries} 次: ${err instanceof Error ? err.message : "未知错误"}`
        );
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxRetries, retryDelayMs]);

  const disconnect = useCallback(() => {
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }
    abortRef.current?.abort();
    abortRef.current = null;
    setConnectionStatus("idle");
    setRetryCount(0);
  }, []);

  return { connect, disconnect, connectionStatus, retryCount };
}
