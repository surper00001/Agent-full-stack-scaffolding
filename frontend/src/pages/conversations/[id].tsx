import { useState, useRef, useEffect, useCallback, type FormEvent, type KeyboardEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft,
  Send,
  Bot,
  User,
  Square,
  Copy,
  Check,
  ChevronDown,
  RefreshCw,
  Clock,
  Library,
  BookOpen,
  FileText,
  X,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import * as conversationsApi from "@/api/conversations";
import * as kbApi from "@/api/knowledge-base";
import type { KnowledgeBaseListItem, KBCitation } from "@/types";

interface LocalMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
}

/** 格式化时间 */
function formatTime(iso?: string) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/** 简易 Markdown 渲染（处理粗体、代码块、换行） */
function SimpleMarkdown({ text }: { text: string }) {
  const html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    // 代码块
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="bg-muted/50 rounded-md p-3 my-2 overflow-x-auto text-xs"><code>$2</code></pre>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code class="bg-muted/50 px-1 py-0.5 rounded text-xs font-mono">$1</code>')
    // 粗体
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    // 斜体
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    // 换行
    .replace(/\n/g, "<br/>");

  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

/**
 * 对话详情页 — 企业级聊天 UX
 *
 * 功能：
 * - SSE 流式输出，实时逐字渲染
 * - 中断/继续对话
 * - 加载历史消息
 * - Markdown 渲染
 * - 复制消息
 * - 键盘快捷键（Enter 发送，Shift+Enter 换行，Esc 取消）
 * - 自动滚动 + 回到底部按钮
 */
export default function ConversationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // KB 选择器
  const [kbList, setKbList] = useState<KnowledgeBaseListItem[]>([]);
  const [activeKbId, setActiveKbId] = useState<string | null>(null);
  const [activeKbName, setActiveKbName] = useState<string>("");
  const [showKbPicker, setShowKbPicker] = useState(false);
  const [citations, setCitations] = useState<KBCitation[]>([]);
  const kbPickerRef = useRef<HTMLDivElement>(null);

  // 加载 KB 列表
  useEffect(() => {
    kbApi.listKBs({ page: 1, page_size: 50 }).then((res) => {
      setKbList(res.data.items);
    }).catch(() => {});
  }, []);

  // KB 选择器的页面外点击关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (kbPickerRef.current && !kbPickerRef.current.contains(e.target as Node)) {
        setShowKbPicker(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectKb = (kb: KnowledgeBaseListItem | null) => {
    if (kb) {
      setActiveKbId(kb.id);
      setActiveKbName(kb.name);
    } else {
      setActiveKbId(null);
      setActiveKbName("");
    }
    setShowKbPicker(false);
    setCitations([]);
  };

  // 加载历史消息（可恢复）
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setIsLoadingHistory(true);
      try {
        const msgsRes = await conversationsApi.getMessagesCursor(id, null, 50, "backward");
        if (cancelled) return;
        const items = msgsRes.data.items ?? [];
        setMessages(
          items.map((m) => ({
            id: m.id,
            role: m.role as LocalMessage["role"],
            content: m.content,
            created_at: m.created_at,
          })),
        );
      } catch {
        // 对话可能不存在
      } finally {
        if (!cancelled) setIsLoadingHistory(false);
      }
    })();
    return () => { cancelled = true; };
  }, [id]);

  // 自动滚动
  useEffect(() => {
    if (isAtBottom) {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages, streamContent, isAtBottom]);

  // 监听滚动位置
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setIsAtBottom(isBottom);
  }, []);

  const scrollToBottom = () => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
    setIsAtBottom(true);
  };

  // 中断生成
  const handleStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    // 保存已生成的部分
    if (streamContent) {
      const partial: LocalMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: streamContent + "\n\n*[已中断]*",
      };
      setMessages((prev) => [...prev, partial]);
    }
    setStreamContent("");
  };

  // 发送消息（流式 V2 — 支持 KB 检索）
  const handleSend = async (e?: FormEvent) => {
    e?.preventDefault();
    const content = input.trim();
    if (!content || isStreaming || !id) return;

    const userMsg: LocalMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: (activeKbId ? `[@${activeKbName}] ` : "") + content,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);
    setStreamContent("");
    setCitations([]);

    const controller = new AbortController();
    abortRef.current = controller;

    let full = "";
    try {
      for await (const event of conversationsApi.streamMessageV2(
        id, content, controller.signal, "agent", null, activeKbId,
      )) {
        if (event.type === "delta") {
          full += event.data as string;
          setStreamContent(full);
        } else if (event.type === "tool_result") {
          // 解析 KB 检索结果，提取引用
          const toolResults = event.data as Array<{
            name?: string; result?: string; status?: string;
          }>;
          for (const tc of toolResults) {
            if (tc.name === "search_knowledge_base" && tc.result) {
              try {
                const parsed = JSON.parse(tc.result);
                if (parsed.results && Array.isArray(parsed.results)) {
                  setCitations(parsed.results);
                }
              } catch { /* JSON parse error */ }
            }
          }
        }
      }
      // 完成
      const assistantMsg: LocalMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: full,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") return;
      const errorMsg: LocalMessage = {
        id: crypto.randomUUID(),
        role: "system",
        content: `发送失败: ${(err as Error).message || "未知错误"}`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsStreaming(false);
      setStreamContent("");
      abortRef.current = null;
    }
  };

  // 重新生成最后一条 assistant 回复
  const handleRegenerate = async () => {
    if (isStreaming) return;
    // 移除最后一条 assistant 消息
    const lastAssistantIdx = [...messages].reverse().findIndex((m) => m.role === "assistant");
    if (lastAssistantIdx < 0) return;
    const actualIdx = messages.length - 1 - lastAssistantIdx;
    const lastUserMsg = messages.slice(0, actualIdx).reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;

    setMessages((prev) => prev.slice(0, actualIdx));
    setInput(lastUserMsg.content);
    setTimeout(() => handleSend(), 50);
  };

  // 键盘快捷键
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === "Escape" && isStreaming) {
      e.preventDefault();
      handleStop();
    }
  };

  // 复制消息
  const handleCopy = async (content: string, msgId: string) => {
    await navigator.clipboard.writeText(content);
    setCopiedId(msgId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      {/* 顶部栏 */}
      <div className="flex items-center gap-3 border-b pb-3">
        <Link to="/conversations">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div className="flex-1">
          <h1 className="text-lg font-bold">对话</h1>
          {!isLoadingHistory && (
            <p className="text-xs text-muted-foreground">
              {messages.length} 条消息
            </p>
          )}
        </div>
        {messages.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRegenerate}
            disabled={isStreaming}
            className="h-8 gap-1.5 text-xs"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重新生成
          </Button>
        )}
      </div>

      {/* 消息区 */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="app-scrollbar flex-1 overflow-y-auto py-4 space-y-1"
      >
        {isLoadingHistory && (
          <div className="flex h-full items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-3 border-primary border-t-transparent" />
              <p className="text-sm text-muted-foreground">加载历史消息...</p>
            </div>
          </div>
        )}

        {!isLoadingHistory && messages.length === 0 && !isStreaming && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center space-y-3">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-muted">
                <Bot className="h-8 w-8 text-muted-foreground/40" />
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">开始新的对话</p>
                <p className="text-xs text-muted-foreground/60 mt-1">
                  输入你的问题，AI 将为你提供帮助
                </p>
              </div>
            </div>
          </div>
        )}

        {/* 历史消息 */}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isCopied={copiedId === msg.id}
            onCopy={() => handleCopy(msg.content, msg.id)}
          />
        ))}

        {/* 流式输出 */}
        {isStreaming && streamContent && (
          <div>
            <MessageBubble
              message={{ id: "stream", role: "assistant", content: streamContent }}
              isStreaming
              isCopied={false}
              onCopy={() => {}}
            />
            {citations.length > 0 && <CitationCards citations={citations} />}
          </div>
        )}

        {/* 等待 LLM 首 token */}
        {isStreaming && !streamContent && (
          <div className="flex items-center gap-3 px-4 py-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted">
              <Bot className="h-4 w-4" />
            </div>
            <div className="flex items-center gap-1">
              <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "0ms" }} />
              <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "150ms" }} />
              <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        )}
      </div>

      {/* 回到底部按钮 */}
      {!isAtBottom && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-28 left-1/2 -translate-x-1/2 rounded-full bg-background border shadow-md p-2 hover:bg-muted transition-colors z-10"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      )}

      {/* 输入区 */}
      <form onSubmit={handleSend} className="border-t pt-3">
        {/* Active KB Tag */}
        {activeKbId && (
          <div className="flex items-center gap-1 mb-2">
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-900/30 px-2.5 py-0.5 text-[11px] font-medium text-blue-700 dark:text-blue-400">
              <BookOpen className="h-3 w-3" />
              {activeKbName}
              <button
                type="button"
                onClick={() => selectKb(null)}
                className="ml-0.5 rounded-full p-0.5 hover:bg-blue-200 dark:hover:bg-blue-800/50 transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
            <span className="text-[10px] text-muted-foreground">
              AI 将检索此知识库回答你的问题
            </span>
          </div>
        )}

        <div className="flex items-end gap-2">
          {/* KB Picker Button */}
          <div className="relative" ref={kbPickerRef}>
            <Button
              type="button"
              variant={activeKbId ? "default" : "ghost"}
              size="icon"
              className={cn(
                "h-11 w-11 shrink-0 transition-all",
                activeKbId && "bg-blue-600 hover:bg-blue-700 text-white"
              )}
              onClick={() => setShowKbPicker(!showKbPicker)}
              title={activeKbId ? `当前知识库: ${activeKbName}` : "选择知识库"}
            >
              <Library className="h-4 w-4" />
            </Button>

            {/* KB Dropdown */}
            {showKbPicker && (
              <div className="absolute bottom-full left-0 mb-2 w-64 rounded-lg border bg-popover shadow-lg z-50 animate-in fade-in slide-in-from-bottom-2">
                <div className="p-2 border-b">
                  <p className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                    <Search className="h-3 w-3" />
                    选择知识库
                  </p>
                </div>
                <div className="max-h-48 overflow-y-auto p-1">
                  <button
                    type="button"
                    onClick={() => selectKb(null)}
                    className={cn(
                      "w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors text-left",
                      !activeKbId ? "bg-primary/10 text-primary font-medium" : "hover:bg-muted"
                    )}
                  >
                    <Bot className="h-4 w-4 shrink-0" />
                    <div className="min-w-0">
                      <p className="truncate">不使用知识库</p>
                      <p className="text-[10px] text-muted-foreground">纯 AI 对话模式</p>
                    </div>
                  </button>
                  {kbList.length === 0 ? (
                    <p className="px-3 py-4 text-xs text-muted-foreground text-center">
                      暂无知识库，请先创建
                    </p>
                  ) : (
                    kbList.map((kb) => (
                      <button
                        key={kb.id}
                        type="button"
                        onClick={() => selectKb(kb)}
                        className={cn(
                          "w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors text-left",
                          activeKbId === kb.id
                            ? "bg-primary/10 text-primary font-medium"
                            : "hover:bg-muted"
                        )}
                      >
                        <BookOpen className="h-4 w-4 shrink-0" />
                        <div className="min-w-0">
                          <p className="truncate">{kb.name}</p>
                          <p className="text-[10px] text-muted-foreground">
                            {kb.document_count} 文档 · {kb.total_chunks} 分块
                          </p>
                        </div>
                      </button>
                    ))
                  )}
                </div>
                {kbList.length > 0 && (
                  <div className="border-t p-2">
                    <Link
                      to="/kb"
                      className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                      onClick={() => setShowKbPicker(false)}
                    >
                      <Library className="h-3 w-3" />
                      管理知识库
                    </Link>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              placeholder={
                isStreaming
                  ? "AI 正在回复中..."
                  : activeKbId
                    ? `向「${activeKbName}」提问... (Enter 发送)`
                    : "输入消息... (Enter 发送，Shift+Enter 换行)"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              rows={1}
              className="w-full resize-none rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm shadow-sm placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              style={{ minHeight: "2.75rem", maxHeight: "8rem" }}
              onInput={(e) => {
                const el = e.currentTarget;
                el.style.height = "auto";
                el.style.height = Math.min(el.scrollHeight, 128) + "px";
              }}
            />
          </div>

          {isStreaming ? (
            <Button
              type="button"
              variant="destructive"
              size="icon"
              onClick={handleStop}
              className="h-11 w-11 shrink-0 animate-pulse"
              title="停止生成 (Esc)"
            >
              <Square className="h-4 w-4" fill="currentColor" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim()}
              className="h-11 w-11 shrink-0 transition-all active:scale-95"
              title="发送 (Enter)"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <p className="mt-1.5 text-center text-[10px] text-muted-foreground/50">
          Enter 发送 · Shift+Enter 换行 · Esc 取消生成
        </p>
      </form>
    </div>
  );
}

/** 消息气泡 */
function MessageBubble({
  message,
  isStreaming,
  isCopied,
  onCopy,
}: {
  message: LocalMessage;
  isStreaming?: boolean;
  isCopied: boolean;
  onCopy: () => void;
}) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center px-4 py-2">
        <span className="text-xs text-destructive/70 bg-destructive/5 rounded-full px-3 py-1">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("group flex gap-3 px-4 py-2 hover:bg-muted/20 transition-colors", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-medium",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Content */}
      <div className={cn("flex max-w-[75%] flex-col", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground rounded-tr-md"
              : "bg-muted/60 rounded-tl-md",
            isStreaming && "border border-dashed border-primary/30 bg-muted/40",
          )}
        >
          {isStreaming ? (
            <SimpleMarkdown text={message.content} />
          ) : isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <SimpleMarkdown text={message.content} />
          )}
        </div>

        {/* Actions row */}
        <div className={cn("flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity", isUser && "flex-row-reverse")}>
          {message.created_at && (
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground/50">
              <Clock className="h-3 w-3" />
              {formatTime(message.created_at)}
            </span>
          )}
          {!isUser && !isStreaming && message.content && (
            <button
              onClick={onCopy}
              className="rounded p-0.5 text-muted-foreground/50 hover:text-foreground transition-colors"
              title="复制"
            >
              {isCopied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** 引用卡片 — 展示 KB 检索结果 */
function CitationCards({ citations }: { citations: KBCitation[] }) {
  const [expanded, setExpanded] = useState(false);
  const displayCitations = expanded ? citations : citations.slice(0, 3);

  if (citations.length === 0) return null;

  return (
    <div className="px-4 pb-2">
      <div className="max-w-[75%] ml-11 space-y-2">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
            <BookOpen className="h-3.5 w-3.5" />
            引用来源 ({citations.length})
          </div>
          {citations.length > 3 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-[10px] text-primary hover:underline"
            >
              {expanded ? "收起" : `展开全部 ${citations.length} 条`}
            </button>
          )}
        </div>

        <div className="space-y-1.5">
          {displayCitations.map((cite, i) => (
            <div
              key={cite.chunk_id || i}
              className="flex items-start gap-2 rounded-lg border bg-background/60 p-2.5 text-xs hover:border-primary/30 hover:bg-background transition-colors cursor-default group"
            >
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-blue-100 dark:bg-blue-900/30 text-[10px] font-bold text-blue-700 dark:text-blue-400">
                {i + 1}
              </div>
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                  <span className="font-medium truncate">{cite.source}</span>
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    第{cite.page}页
                  </span>
                  <span className="text-[10px] shrink-0 rounded-full bg-green-100 dark:bg-green-900/30 px-1.5 py-0.5 text-green-700 dark:text-green-400 font-mono">
                    {Math.round(cite.score * 100)}%
                  </span>
                </div>
                {cite.section_title && (
                  <p className="text-[10px] text-muted-foreground/70">
                    {cite.section_title}
                  </p>
                )}
                <p className="text-[11px] leading-relaxed text-muted-foreground line-clamp-3 group-hover:line-clamp-none">
                  {cite.content}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
