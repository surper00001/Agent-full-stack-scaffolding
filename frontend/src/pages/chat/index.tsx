import { useState, useEffect, type KeyboardEvent, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAgentStore } from "@/stores";
import { useConversations } from "@/hooks";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { Button } from "@/components/ui/button";
import { Bot, ArrowRight, Sparkles, Send, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types";

export default function ChatHomePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const kbFromUrl = searchParams.get("kb");
  const modeFromUrl = searchParams.get("mode");
  const { agents, isLoading, fetchAgents } = useAgentStore();
  const { createConversation } = useConversations();
  const [input, setInput] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    fetchAgents(1, 100);
  }, [fetchAgents]);

  /** 快速开始综合对话 */
  const handleQuickStart = async (e?: FormEvent) => {
    e?.preventDefault();
    const content = input.trim();
    if (!content || isCreating) return;

    setIsCreating(true);
    try {
      const conv = await createConversation("新对话", "general", kbFromUrl);
      const params = new URLSearchParams();
      params.set("q", content);
      if (kbFromUrl) params.set("kb", kbFromUrl);
      if (modeFromUrl) params.set("mode", modeFromUrl);
      else if (kbFromUrl) params.set("mode", "agent");
      navigate(`/chat/${conv.id}?${params.toString()}`);
    } finally {
      setIsCreating(false);
    }
  };

  /** 选择专业智能体开始对话 */
  const handleAgentChat = async (agent: Agent) => {
    setIsCreating(true);
    try {
      const conv = await createConversation(`${agent.name} 对话`, agent.agent_type, kbFromUrl);
      const params = new URLSearchParams();
      if (kbFromUrl) params.set("kb", kbFromUrl);
      if (modeFromUrl) params.set("mode", modeFromUrl);
      else if (kbFromUrl) params.set("mode", "agent");
      const suffix = params.toString() ? `?${params.toString()}` : "";
      navigate(`/chat/${conv.id}${suffix}`);
    } finally {
      setIsCreating(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleQuickStart();
    }
  };

  const specializedAgents = agents.filter((a) => a.agent_type !== "general");

  return (
    <div className="flex h-full flex-col bg-background">
      {/* 中间欢迎区 */}
      <div className="flex flex-1 items-center justify-center px-4">
        <div className="w-full max-w-2xl space-y-8">
          {/* 欢迎语 */}
          <div className="text-center space-y-3">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
              <Sparkles className="h-7 w-7 text-primary" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">有什么可以帮你的？</h1>
            <p className="text-sm text-muted-foreground">
              我是<strong>综合智能助手</strong>，可以处理编程、写作、分析、学习等各类日常任务
            </p>
          </div>

          {/* 快捷输入区 */}
          <form onSubmit={handleQuickStart} className="relative">
            <div className="flex items-end gap-2 rounded-2xl border bg-background px-4 py-3 shadow-sm transition-shadow focus-within:shadow-md focus-within:border-primary/30">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入你的问题，直接开始对话... (Enter 发送，Shift+Enter 换行)"
                rows={2}
                disabled={isCreating}
                className="flex-1 resize-none bg-transparent text-sm placeholder:text-muted-foreground/50 focus:outline-none disabled:opacity-50"
                style={{ minHeight: "3rem", maxHeight: "8rem" }}
                onInput={(e) => {
                  const el = e.currentTarget;
                  el.style.height = "auto";
                  el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
                }}
              />
              <Button
                type="submit"
                size="icon"
                disabled={!input.trim() || isCreating}
                className="h-10 w-10 shrink-0 rounded-xl"
              >
                {isCreating ? (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
            <div className="flex justify-center mt-2 gap-2 text-[11px] text-muted-foreground/40">
              <kbd className="rounded border bg-muted/50 px-1.5 py-0.5 font-mono">Enter</kbd>
              <span>发送</span>
              <kbd className="rounded border bg-muted/50 px-1.5 py-0.5 font-mono">Shift + Enter</kbd>
              <span>换行</span>
            </div>
          </form>

          {/* 专业智能体区 — 仅当有专业智能体时显示 */}
          {specializedAgents.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground/60 flex items-center gap-1">
                  <MessageSquare className="h-3 w-3" />
                  试试专业智能体
                </span>
                <div className="h-px flex-1 bg-border" />
              </div>

              {isLoading ? (
                <div className="flex justify-center py-4">
                  <LoadingSpinner size="sm" />
                </div>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  {specializedAgents.map((agent) => (
                    <button
                      key={agent.id}
                      onClick={() => handleAgentChat(agent)}
                      disabled={isCreating}
                      className={cn(
                        "group flex items-center gap-3 rounded-lg border bg-card/50 px-3 py-2.5 text-left",
                        "transition-all hover:border-primary/30 hover:bg-card hover:shadow-sm",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        isCreating && "pointer-events-none opacity-50",
                      )}
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                        <Bot className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-xs">{agent.name}</h3>
                        <p className="mt-0.5 text-[10px] text-muted-foreground line-clamp-1">
                          {agent.agent_type === "creative" ? "AI 短视频创作顾问团" : agent.agent_type === "mindmap" ? "思维导图生成与编辑助手" : agent.agent_type}
                        </p>
                      </div>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/20 opacity-0 transition-all group-hover:opacity-100 group-hover:text-primary group-hover:translate-x-0.5" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 底部提示 */}
      <div className="shrink-0 py-3 text-center">
        <p className="text-[11px] text-muted-foreground/40">
          直接输入问题即可开始，综合智能助手将为你提供帮助
        </p>
      </div>
    </div>
  );
}
