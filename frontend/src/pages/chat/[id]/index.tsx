import { useState, useRef, useEffect, useCallback, type FormEvent, type KeyboardEvent } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import type { ChatMode } from "@/types";
import {
  Send, Bot, Square, Check, ChevronDown, RefreshCw,
  Wrench, Loader2, Download, ListChecks, FileText, Zap, MessageSquare, Brain, Workflow,
  Library, BookOpen, X, ImagePlus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import * as conversationsApi from "@/api/conversations";
import { API_BASE_URL, CONTEXT_MAX_TOKENS } from "@/lib/constants";
import type { ContextUsageSnapshot, ToolCall } from "@/types";
import { useKBStore, useConversationStore } from "@/stores";
import { CitationCards, parseKBCitations, parseCitationsFromArray, type KBCitation } from "@/components/kb/citation-cards";
import { MessageBubble } from "@/components/chat/message-bubble";
import { MindMapRenderer, type MindMap } from "@/components/kb/mindmap-renderer";
import { extractMindmapFromMetadata, parseMindmapFromContent } from "@/components/kb/mindmap-utils";

// ---- Types ----

interface PlanStep {
  step: number;
  action: string;
  tool: string;
  expected_output: string;
}

interface FileOutput {
  filename: string;
  download_url: string;
  label: string;
  mime_type?: string;
  size_display?: string;
}

interface LocalMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  tool_calls?: ToolCall[];
  files?: FileOutput[];
  citations?: KBCitation[];
  mindmap?: MindMap;
}

// ---- Helpers ----

function formatTime(iso?: string) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function getDownloadUrl(url: string) {
  if (url.startsWith("http")) return url;
  return `${API_BASE_URL}${url}`;
}

// ---- Markdown Renderer: replaced with SafeMarkdown (react-markdown + rehype-sanitize) ----

function mapMessageToLocal(m: {
  id: string;
  role: string;
  content: string;
  created_at: string;
  metadata_?: Record<string, unknown> | null;
}): LocalMessage {
  const citations = parseCitationsFromArray(m.metadata_?.citations);
  // 优先从 metadata 取 mindmap，否则从内容末尾 JSON 代码块解析
  const mindmap =
    extractMindmapFromMetadata(m.metadata_ as Record<string, unknown> | null | undefined) ||
    parseMindmapFromContent(m.content);
  return {
    id: m.id,
    role: m.role as LocalMessage["role"],
    content: m.content,
    created_at: m.created_at,
    citations: citations.length > 0 ? citations : undefined,
    mindmap: mindmap || undefined,
  };
}

export default function ChatDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const { kbList, fetchKBList } = useKBStore();
  const { refreshConversations } = useConversationStore();

  // 图片上传
  interface UploadedImage {
    imageId: string;
    filename: string;
    preview: string | null;
    objectUrl: string;
  }
  const [uploadedImages, setUploadedImages] = useState<UploadedImage[]>([]);
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const handleImageSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !id) return;
    setIsUploadingImage(true);
    const newImages: UploadedImage[] = [];
    for (const file of Array.from(files)) {
      try {
        const result = await conversationsApi.uploadChatImage(id, file);
        newImages.push({
          imageId: result.image_id,
          filename: result.filename,
          preview: result.preview,
          objectUrl: URL.createObjectURL(file),
        });
      } catch {
        // 单张上传失败，继续处理剩余
      }
    }
    setUploadedImages((prev) => [...prev, ...newImages]);
    setIsUploadingImage(false);
    if (imageInputRef.current) imageInputRef.current.value = "";
  }, [id]);

  const removeImage = useCallback((imageId: string) => {
    setUploadedImages((prev) => {
      const img = prev.find((i) => i.imageId === imageId);
      if (img) URL.revokeObjectURL(img.objectUrl);
      return prev.filter((i) => i.imageId !== imageId);
    });
  }, []);

  const clearUploadedImages = useCallback(() => {
    setUploadedImages((prev) => {
      for (const img of prev) URL.revokeObjectURL(img.objectUrl);
      return [];
    });
  }, []);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [conversationTitle, setConversationTitle] = useState("");

  // Pagination
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMoreMessages, setHasMoreMessages] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // Chat mode: ask | agent | plan
  const [chatMode, setChatMode] = useState<ChatMode>(() => {
    const mode = searchParams.get("mode");
    return mode === "ask" || mode === "agent" || mode === "plan" ? mode : "agent";
  });
  const pendingQueryRef = useRef<string | null>(searchParams.get("q"));
  const hasAutoSentRef = useRef(false);

  // Plan display
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [planSummary, setPlanSummary] = useState("");

  // Tool calls in current stream
  const [liveToolCalls, setLiveToolCalls] = useState<ToolCall[]>([]);

  // File outputs in current stream
  const [liveFiles, setLiveFiles] = useState<FileOutput[]>([]);
  const [liveCitations, setLiveCitations] = useState<KBCitation[]>([]);
  const [liveMindmap, setLiveMindmap] = useState<MindMap | null>(null);

  // 知识库选择（Agent/Plan 模式可用）
  const [activeKbId, setActiveKbId] = useState<string | null>(null);
  const [activeKbName, setActiveKbName] = useState("");
  const [showKbPicker, setShowKbPicker] = useState(false);
  const kbPickerRef = useRef<HTMLDivElement>(null);

  // Token usage
  const [tokenUsage, setTokenUsage] = useState({ used: 0, quota: CONTEXT_MAX_TOKENS });

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchKBList(1, 50);
  }, [fetchKBList]);

  useEffect(() => {
    const kbFromUrl = searchParams.get("kb");
    if (kbFromUrl) {
      setActiveKbId(kbFromUrl);
      const found = kbList.find((k) => k.id === kbFromUrl);
      if (found) setActiveKbName(found.name);
    }
    const qFromUrl = searchParams.get("q");
    if (qFromUrl) {
      setInput(qFromUrl);
      pendingQueryRef.current = qFromUrl;
    }
    const modeFromUrl = searchParams.get("mode");
    if (modeFromUrl === "ask" || modeFromUrl === "agent" || modeFromUrl === "plan") {
      setChatMode(modeFromUrl);
    }
  }, [searchParams, kbList]);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (kbPickerRef.current && !kbPickerRef.current.contains(e.target as Node)) {
        setShowKbPicker(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const selectKb = (kb: { id: string; name: string } | null) => {
    if (kb) {
      setActiveKbId(kb.id);
      setActiveKbName(kb.name);
    } else {
      setActiveKbId(null);
      setActiveKbName("");
    }
    setShowKbPicker(false);
  };

  const kbIdForRequest = activeKbId ? activeKbId : null;

  // ---- Initial load ----
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setIsLoadingHistory(true);
      try {
        const [convRes, msgsRes] = await Promise.all([
          conversationsApi.getConversation(id),
          conversationsApi.getMessagesCursor(id, null, 50, "backward"),
        ]);
        if (cancelled) return;
        setConversationTitle(convRes.data.title || "对话");
        if (convRes.data.knowledge_base_id) {
          setActiveKbId(convRes.data.knowledge_base_id);
          setActiveKbName(convRes.data.knowledge_base_name || convRes.data.knowledge_base_id);
        }
        const items = msgsRes.data.items ?? [];
        const msgs: LocalMessage[] = items.map(mapMessageToLocal);
        setMessages(msgs);
        setCursor(msgsRes.data.next_cursor);
        setHasMoreMessages(!!msgsRes.data.next_cursor);
      } catch { /* ignore */ }
      finally { if (!cancelled) setIsLoadingHistory(false); }
    })();
    return () => { cancelled = true; };
  }, [id]);

  // 从 KB 检索 Tab 带 ?q= 跳转时自动发送首条
  useEffect(() => {
    if (isLoadingHistory || isStreaming || !id || hasAutoSentRef.current) return;
    const q = pendingQueryRef.current?.trim();
    if (!q) return;
    hasAutoSentRef.current = true;
    pendingQueryRef.current = null;
    void handleSend(undefined, q);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoadingHistory, isStreaming, id]);

  // ---- Token usage polling ----
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const fetchCtx = async () => {
      try {
        const res = await conversationsApi.getContextInfo(id!);
        if (cancelled) return;
        setTokenUsage({ used: res.data.total_tokens, quota: res.data.max_context });
      } catch { /* ignore */ }
    };
    fetchCtx();
    const interval = setInterval(fetchCtx, 30_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [id]);

  // ---- Infinite scroll ----
  const loadMoreMessages = useCallback(async () => {
    if (!id || isLoadingMore || !hasMoreMessages || isLoadingHistory) return;
    setIsLoadingMore(true);
    const prevHeight = scrollRef.current?.scrollHeight || 0;
    try {
      const res = await conversationsApi.getMessagesCursor(id, cursor, 50, "backward");
      const items = res.data.items || [];
      const newMessages: LocalMessage[] = items.map(mapMessageToLocal);
      setMessages((prev) => [...newMessages, ...prev]);
      setCursor(res.data.next_cursor);
      setHasMoreMessages(!!res.data.next_cursor);
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight - prevHeight;
        }
      });
    } catch { /* ignore */ }
    finally { setIsLoadingMore(false); }
  }, [id, cursor, isLoadingMore, hasMoreMessages, isLoadingHistory]);

  useEffect(() => {
    const el = topSentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMoreMessages(); },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMoreMessages]);

  // ---- Auto scroll ----
  useEffect(() => {
    if (isAtBottom) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, streamContent, liveToolCalls, isAtBottom]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setIsAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  }, []);

  const scrollToBottom = () => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    setIsAtBottom(true);
  };

  // ---- Stream ----
  const handleStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    if (streamContent) {
      setMessages((prev) => [...prev, {
        id: crypto.randomUUID(), role: "assistant",
        content: streamContent + "\n\n*[已中断]*",
      }]);
    }
    setStreamContent("");
    setLiveToolCalls([]);
    setLiveFiles([]);
    setPlanSteps([]);
  };

  const handleSend = async (e?: FormEvent, overrideContent?: string) => {
    e?.preventDefault();
    const content = (overrideContent ?? input).trim();
    if (!content || isStreaming || !id) return;

    setMessages((prev) => [...prev, {
      id: crypto.randomUUID(), role: "user", content,
      created_at: new Date().toISOString(),
    }]);
    setInput("");
    setIsStreaming(true);
    setStreamContent("");
    setLiveToolCalls([]);
    setLiveFiles([]);
    setLiveCitations([]);
    setPlanSteps([]);
    setPlanSummary("");

    const controller = new AbortController();
    abortRef.current = controller;

    let full = "";
    const files: FileOutput[] = [];
    let messageCitations: KBCitation[] = [];
    try {
      const imageIds = uploadedImages.map((img) => img.imageId);
      if (imageIds.length > 0) {
        clearUploadedImages();
      }

      for await (const event of conversationsApi.streamMessageV2(
        id, content, controller.signal, chatMode, null, kbIdForRequest,
        imageIds.length > 0 ? imageIds : null,
      )) {
        if (event.type === "plan") {
          const plan = event.data as { steps: PlanStep[]; summary: string };
          setPlanSteps(plan.steps || []);
          setPlanSummary(plan.summary || "");
        } else if (event.type === "delta") {
          full += event.data as string;
          setStreamContent(full);
        } else if (event.type === "file") {
          const f = event.data as FileOutput;
          files.push(f);
          setLiveFiles([...files]);
        } else if (event.type === "tool_call") {
          const calls = event.data as ToolCall[];
          setLiveToolCalls(calls.map((tc) => ({ ...tc, status: tc.status || "running" })));
        } else if (event.type === "rag_context") {
          const rag = event.data as { citations?: unknown[] };
          const cites = parseCitationsFromArray(rag.citations);
          if (cites.length) {
            messageCitations = cites;
            setLiveCitations(cites);
          }
        } else if (event.type === "tool_result") {
          const results = event.data as ToolCall[];
          setLiveToolCalls((prev) =>
            prev.map((tc) => {
              const match = results.find((r) => r.id === tc.id);
              return match ? { ...tc, result: match.result, status: "completed" } : tc;
            }),
          );
          for (const tc of results) {
            if (tc.name === "search_knowledge_base" && typeof tc.result === "string") {
              const cites = parseKBCitations(tc.result);
              if (cites.length) {
                messageCitations = cites;
                setLiveCitations(cites);
              }
            }
          }
        } else if (event.type === "done") {
          const meta = event.data as {
            conversation_id: string;
            token_usage?: { total_tokens: number };
            context_usage?: ContextUsageSnapshot;
          };
          if (meta.context_usage) {
            setTokenUsage({
              used: meta.context_usage.used_tokens,
              quota: meta.context_usage.max_tokens,
            });
          }
        }
      }
      if (full) {
        const parsedMindmap = parseMindmapFromContent(full);
        if (parsedMindmap) setLiveMindmap(parsedMindmap);
        setMessages((prev) => [...prev, {
          id: crypto.randomUUID(), role: "assistant", content: full,
          created_at: new Date().toISOString(),
          files: files.length > 0 ? files : undefined,
          citations: messageCitations.length > 0 ? messageCitations : undefined,
          mindmap: parsedMindmap || undefined,
        }]);
        refreshConversations();
      }
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") return;
      setMessages((prev) => [...prev, {
        id: crypto.randomUUID(), role: "system",
        content: `发送失败: ${(err as Error).message || "未知错误"}`,
      }]);
    } finally {
      setIsStreaming(false);
      setStreamContent("");
      setLiveToolCalls([]);
      setLiveFiles([]);
      setLiveCitations([]);
      setLiveMindmap(null);
      setPlanSteps([]);
      abortRef.current = null;
    }
  };

  const handleRegenerate = async () => {
    if (isStreaming) return;
    const lastAssistantIdx = [...messages].reverse().findIndex((m) => m.role === "assistant");
    if (lastAssistantIdx < 0) return;
    const actualIdx = messages.length - 1 - lastAssistantIdx;
    const lastUserMsg = messages.slice(0, actualIdx).reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;
    setMessages((prev) => prev.slice(0, actualIdx));
    setInput(lastUserMsg.content);
    setTimeout(() => handleSend(), 50);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === "Escape" && isStreaming) {
      e.preventDefault();
      handleStop();
    }
  };

  const usagePct = tokenUsage.quota > 0 ? tokenUsage.used / tokenUsage.quota : 0;

  // ---- Render ----

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      {conversationTitle && !isLoadingHistory && (
        <div className="flex items-center justify-between shrink-0 border-b px-5 py-2.5 gap-3 bg-background/80 backdrop-blur-sm">
          <div className="flex items-center gap-2 min-w-0">
            <h2 className="text-sm font-medium text-foreground/80 truncate">{conversationTitle}</h2>
            <span className={cn(
              "shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-medium",
              chatMode === "plan" && "bg-amber-500/10 text-amber-600",
              chatMode === "agent" && "bg-emerald-500/10 text-emerald-600",
              chatMode === "ask" && "bg-zinc-500/10 text-zinc-600",
            )}>
              {chatMode === "plan" ? "Plan" : chatMode === "agent" ? "Agent" : "Ask"}
            </span>
            {activeKbId && (
              <span className="shrink-0 inline-flex items-center gap-1 rounded-md bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
                <BookOpen className="h-3 w-3" />
                {activeKbName}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 shrink-0">
            {/* Token gauge */}
            <div className="flex items-center gap-2">
              <div className={cn("h-1.5 rounded-full transition-all duration-500",
                usagePct > 0.9 ? "w-14 bg-destructive" : usagePct > 0.7 ? "w-12 bg-amber-500" : "w-10 bg-emerald-500",
              )} />
              <span className="text-[10px] text-muted-foreground tabular-nums font-mono">
                {formatTokens(tokenUsage.used)}/{formatTokens(tokenUsage.quota)}
              </span>
              <span className={cn("text-[10px] font-mono tabular-nums",
                usagePct > 0.9 ? "text-destructive" : usagePct > 0.7 ? "text-amber-500" : "text-emerald-500",
              )}>
                {Math.round(usagePct * 100)}%
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-muted-foreground/50 font-mono">{messages.length}</span>
              <Button variant="ghost" size="sm" onClick={handleRegenerate} disabled={isStreaming}
                className="h-7 gap-1 text-xs hover:bg-muted">
                <RefreshCw className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="app-scrollbar flex-1 overflow-y-auto"
      >
        <div ref={topSentinelRef} className="h-1" />

        {isLoadingMore && (
          <div className="flex justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        )}

        {isLoadingHistory && (
          <div className="flex h-full items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-foreground/20 border-t-foreground" />
              <p className="text-sm text-muted-foreground">加载历史消息...</p>
            </div>
          </div>
        )}

        {!isLoadingHistory && messages.length === 0 && !isStreaming && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center space-y-5 px-4 animate-fade-in-up">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-foreground/[0.04] ring-1 ring-foreground/[0.06]">
                {chatMode === "plan" ? (
                  <Workflow className="h-7 w-7 text-foreground/60" />
                ) : chatMode === "ask" ? (
                  <MessageSquare className="h-7 w-7 text-foreground/60" />
                ) : (
                  <Zap className="h-7 w-7 text-foreground/60" />
                )}
              </div>
              <div>
                <p className="text-base font-medium text-foreground/80">
                  {chatMode === "plan" ? "Plan + 执行" : chatMode === "ask" ? "快速问答" : "Agent 模式"}
                </p>
                <p className="mt-1.5 text-sm text-muted-foreground max-w-xs">
                  {chatMode === "plan"
                    ? "AI 先规划再逐步执行，适合复杂多步骤任务"
                    : chatMode === "ask"
                    ? "纯语言模型对话，不调用工具，快速轻量"
                    : "ReAct 推理 + 工具调用，适合需要搜索、生成、分析的复杂任务"
                  }
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2 text-xs text-muted-foreground/60">
                <kbd className="rounded-md border bg-muted px-2 py-1 font-mono text-[11px]">Enter</kbd>
                <span className="py-1">发送</span>
                <kbd className="rounded-md border bg-muted px-2 py-1 font-mono text-[11px]">Shift + Enter</kbd>
                <span className="py-1">换行</span>
              </div>
            </div>
          </div>
        )}

        {/* Plan display — only when plan mode was used and plan was received */}
        {planSteps.length > 0 && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 px-6 pt-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600">
                <Workflow className="h-3 w-3" />
                PLAN
              </span>
            </div>
            <PlanCard steps={planSteps} summary={planSummary} />
          </div>
        )}

        {/* Messages */}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            showTime={msg.created_at ? formatTime(msg.created_at) : null}
          />
        ))}

        {/* Live tool calls */}
        {liveToolCalls.length > 0 && (
          <div className="px-6 py-2 space-y-1.5">
            {liveToolCalls.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}

        {liveCitations.length > 0 && isStreaming && (
          <CitationCards citations={liveCitations} />
        )}

        {liveMindmap && isStreaming && (
          <div className="px-4 pb-2">
            <div className="max-w-[75%] ml-11">
              <MindMapRenderer
                data={liveMindmap}
                onSendMessage={(cmd) => handleSend(undefined, cmd)}
              />
            </div>
          </div>
        )}

        {/* Streaming message with typing cursor */}
        {isStreaming && streamContent && (
          <MessageBubble
            message={{ id: "stream", role: "assistant", content: streamContent }}
            isStreaming
          />
        )}

        {/* Live file outputs */}
        {liveFiles.length > 0 && (
          <div className="px-6 py-2 space-y-1.5">
            {liveFiles.map((f, i) => (
              <FileCard key={f.filename + i} file={f} />
            ))}
          </div>
        )}

        {/* Loading dots */}
        {isStreaming && !streamContent && liveToolCalls.length === 0 && (
          <div className="flex items-center gap-3 px-6 py-4 animate-fade-in">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
              <Bot className="h-3.5 w-3.5" />
            </div>
            <TypingDots />
          </div>
        )}
      </div>

      {/* Scroll-to-bottom */}
      {!isAtBottom && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-24 left-1/2 -translate-x-1/2 rounded-full bg-background border shadow-lg p-2 hover:bg-muted transition-all z-10"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      )}

      {/* Input */}
      <div className="shrink-0 border-t bg-background/80 backdrop-blur-sm px-4 py-3">
        <form onSubmit={handleSend} className="mx-auto max-w-3xl">
          {/* Mode selector */}
          <div className="flex items-center gap-1 mb-2">
            <ModeTab
              active={chatMode === "ask"}
              onClick={() => setChatMode("ask")}
              icon={MessageSquare}
              label="Ask"
              hint="纯问答"
            />
            <ModeTab
              active={chatMode === "agent"}
              onClick={() => setChatMode("agent")}
              icon={Brain}
              label="Agent"
              hint="ReAct + 工具"
            />
            <ModeTab
              active={chatMode === "plan"}
              onClick={() => setChatMode("plan")}
              icon={Workflow}
              label="Plan"
              hint="规划 + 执行"
            />
          </div>

          {activeKbId && (
            <div className="flex items-center gap-1 mb-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-900/30 px-2.5 py-0.5 text-[11px] font-medium text-blue-700 dark:text-blue-400">
                <BookOpen className="h-3 w-3" />
                {activeKbName}
                <button type="button" onClick={() => selectKb(null)} className="ml-0.5 rounded-full p-0.5 hover:bg-blue-200/50">
                  <X className="h-3 w-3" />
                </button>
              </span>
              <span className="text-[10px] text-muted-foreground">
                {chatMode === "ask" ? "将自动检索此知识库" : "将检索此知识库，Agent 可补充搜索"}
              </span>
            </div>
          )}

          {/* 图片预览区 */}
          {uploadedImages.length > 0 && (
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              {uploadedImages.map((img) => (
                <div key={img.imageId} className="relative group shrink-0">
                  <img
                    src={img.objectUrl}
                    alt={img.filename}
                    className="h-14 w-14 rounded-lg object-cover border"
                  />
                  <button
                    type="button"
                    onClick={() => removeImage(img.imageId)}
                    className="absolute -top-1.5 -right-1.5 rounded-full bg-destructive text-destructive-foreground p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="h-3 w-3" />
                  </button>
                  {img.preview && (
                    <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] px-1 py-0.5 rounded-b-lg truncate">
                      {img.preview.slice(0, 20)}...
                    </div>
                  )}
                </div>
              ))}
              {isUploadingImage && (
                <span className="h-14 w-14 rounded-lg border flex items-center justify-center">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </span>
              )}
            </div>
          )}

          <div className="flex items-end gap-2">
            <div className="relative shrink-0" ref={kbPickerRef}>
              <input
                ref={imageInputRef}
                type="file"
                multiple
                accept="image/png,image/jpeg,image/jpg,image/bmp,image/webp"
                onChange={handleImageSelect}
                className="hidden"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-11 w-11"
                onClick={() => imageInputRef.current?.click()}
                disabled={isUploadingImage || isStreaming}
                title="上传图片"
              >
                <ImagePlus className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant={activeKbId ? "default" : "ghost"}
                size="icon"
                className={cn("h-11 w-11", activeKbId && "bg-blue-600 hover:bg-blue-700 text-white")}
                onClick={() => setShowKbPicker(!showKbPicker)}
                title="选择知识库"
              >
                <Library className="h-4 w-4" />
              </Button>
              {showKbPicker && (
                <div className="absolute bottom-full left-0 mb-2 w-64 rounded-lg border bg-popover shadow-lg z-50 p-1 max-h-48 overflow-y-auto">
                  <button type="button" onClick={() => selectKb(null)} className="w-full text-left px-3 py-2 text-sm hover:bg-muted rounded-md">
                    不使用知识库
                  </button>
                  {kbList.map((kb) => (
                    <button
                      key={kb.id}
                      type="button"
                      onClick={() => selectKb(kb)}
                      className={cn(
                        "w-full text-left px-3 py-2 text-sm hover:bg-muted rounded-md",
                        activeKbId === kb.id && "bg-primary/10 text-primary",
                      )}
                    >
                      {kb.name}
                    </button>
                  ))}
                  <Link to="/kb" className="block text-center text-[11px] text-muted-foreground py-2 hover:underline">
                    管理知识库
                  </Link>
                </div>
              )}
            </div>
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                placeholder={
                  isStreaming
                    ? "AI 正在回复..."
                    : chatMode === "plan"
                    ? "描述复杂任务，AI 将先规划再执行... (Enter 发送)"
                    : chatMode === "ask"
                    ? "随便问问，快速解答... (Enter 发送)"
                    : "描述你的需求，AI 将调用工具完成... (Enter 发送)"
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isStreaming}
                rows={1}
                className="w-full resize-none rounded-xl border bg-background px-4 py-2.5 text-sm shadow-sm
                  placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1
                  focus-visible:ring-foreground/20 disabled:cursor-not-allowed disabled:opacity-50"
                style={{ minHeight: "2.75rem", maxHeight: "8rem" }}
                onInput={(e) => {
                  const el = e.currentTarget;
                  el.style.height = "auto";
                  el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
                }}
              />
            </div>
            {isStreaming ? (
              <Button type="button" variant="destructive" size="icon" onClick={handleStop}
                className="h-11 w-11 shrink-0 animate-pulse" title="停止 (Esc)">
                <Square className="h-4 w-4" fill="currentColor" />
              </Button>
            ) : (
              <Button type="submit" size="icon" disabled={!input.trim()}
                className={cn(
                  "h-11 w-11 shrink-0 rounded-xl transition-colors",
                  chatMode === "plan" && "bg-amber-600 hover:bg-amber-700",
                  chatMode === "ask" && "bg-zinc-700 hover:bg-zinc-800",
                )}
                title="发送 (Enter)">
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

// ---- Mode Tab ----

function ModeTab({
  active, onClick, icon: Icon, label, hint,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ElementType;
  label: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
        "hover:bg-muted/60",
        active
          ? "bg-foreground/[0.07] text-foreground shadow-sm"
          : "text-muted-foreground/60",
      )}
      title={hint}
    >
      <Icon className={cn("h-3 w-3", active && "text-foreground/80")} />
      <span>{label}</span>
    </button>
  );
}

// ---- Typing Dots ----

function TypingDots() {
  return (
    <div className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-foreground/30"
          style={{
            animation: `typingBounce 1.2s ease-in-out infinite`,
            animationDelay: `${i * 180}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ---- Plan Card ----

function PlanCard({ steps, summary }: { steps: PlanStep[]; summary: string }) {
  const [collapsed, setCollapsed] = useState(false);

  if (steps.length === 0) return null;

  return (
    <div className="px-6 py-3 animate-slide-in-left">
      <div className="rounded-xl border bg-card/50 overflow-hidden">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center gap-2 w-full px-4 py-2.5 text-left hover:bg-muted/50 transition-colors"
        >
          <ListChecks className="h-4 w-4 text-emerald-500" />
          <span className="text-sm font-medium">执行计划</span>
          <span className="text-xs text-muted-foreground">{steps.length} 步骤</span>
          <ChevronDown className={cn("h-3.5 w-3.5 ml-auto text-muted-foreground transition-transform",
            collapsed && "-rotate-90")} />
        </button>
        {!collapsed && (
          <div className="border-t px-4 py-3 space-y-2">
            {summary && (
              <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">{summary}</pre>
            )}
            <div className="space-y-1.5">
              {steps.map((s) => (
                <div key={s.step} className="flex items-start gap-3 text-xs">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600 font-mono text-[11px] font-medium">
                    {s.step}
                  </span>
                  <div className="min-w-0">
                    <span className="text-foreground/80">{s.action}</span>
                    {s.tool && (
                      <code className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                        {s.tool}
                      </code>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- File Card ----

function FileCard({ file }: { file: FileOutput }) {
  return (
    <div className="rounded-lg border bg-card/60 px-4 py-3 animate-slide-in-right">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
          <FileText className="h-4 w-4 text-emerald-600" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{file.filename}</p>
          <p className="text-xs text-muted-foreground">
            {file.size_display || ""} {file.mime_type || ""}
          </p>
        </div>
        <a
          href={getDownloadUrl(file.download_url)}
          download={file.filename}
          className="flex items-center gap-1.5 rounded-lg bg-foreground/[0.05] hover:bg-foreground/[0.1] px-3 py-1.5 text-xs font-medium transition-colors"
        >
          <Download className="h-3.5 w-3.5" />
          下载
        </a>
      </div>
    </div>
  );
}

// ---- Tool Call Card ----

function ToolCallCard({ toolCall }: { toolCall: ToolCall }) {
  return (
    <details className="rounded-lg border bg-muted/20 text-xs group">
      <summary className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-muted/40 select-none">
        <span className={cn(
          "h-1.5 w-1.5 rounded-full shrink-0",
          toolCall.status === "running" && "bg-amber-500 animate-pulse",
          toolCall.status === "completed" && "bg-emerald-500",
          toolCall.status === "error" && "bg-destructive",
        )} />
        <Wrench className="h-3 w-3 text-muted-foreground" />
        <code className="font-mono text-xs">{toolCall.name}</code>
        {toolCall.status === "running" && (
          <span className="text-muted-foreground text-[10px]">执行中...</span>
        )}
        {toolCall.status === "completed" && (
          <Check className="h-3 w-3 text-emerald-500 ml-auto" />
        )}
      </summary>
      <div className="px-3 py-2 border-t space-y-1.5 bg-background/50">
        <div>
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">参数</span>
          <pre className="mt-0.5 bg-muted/50 px-2 py-1 rounded text-[11px] font-mono overflow-x-auto">
            {JSON.stringify(toolCall.arguments, null, 2)}
          </pre>
        </div>
        {toolCall.result !== undefined && (
          <div>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">结果</span>
            <pre className="mt-0.5 bg-muted/50 px-2 py-1 rounded text-[11px] font-mono overflow-x-auto max-h-40 overflow-y-auto leading-relaxed">
              {typeof toolCall.result === "string" ? toolCall.result : JSON.stringify(toolCall.result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </details>
  );
}

// MessageBubble 已提取至 @/components/chat/message-bubble.tsx
