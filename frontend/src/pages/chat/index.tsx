import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAgentStore } from "@/stores";
import { useConversations } from "@/hooks";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { Bot, ArrowRight, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types";

export default function ChatHomePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const kbFromUrl = searchParams.get("kb");
  const qFromUrl = searchParams.get("q");
  const modeFromUrl = searchParams.get("mode");
  const { agents, isLoading, fetchAgents } = useAgentStore();
  const { createConversation } = useConversations();
  const [creating, setCreating] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents(1, 100);
  }, [fetchAgents]);

  const handleStartChat = async (agent: Agent) => {
    setCreating(agent.id);
    try {
      const conv = await createConversation(`${agent.name} 对话`, agent.agent_type, kbFromUrl);
      const params = new URLSearchParams();
      if (kbFromUrl) params.set("kb", kbFromUrl);
      if (qFromUrl) params.set("q", qFromUrl);
      if (modeFromUrl) params.set("mode", modeFromUrl);
      else if (kbFromUrl) params.set("mode", "agent");
      const suffix = params.toString() ? `?${params.toString()}` : "";
      navigate(`/chat/${conv.id}${suffix}`);
    } finally {
      setCreating(null);
    }
  };

  return (
    <div className="flex h-full items-center justify-center px-4">
      <div className="w-full max-w-2xl space-y-8 text-center">
        <div className="space-y-3">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <Sparkles className="h-7 w-7 text-primary" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">有什么可以帮你的？</h1>
          <p className="text-sm text-muted-foreground">选择一个智能体开始对话</p>
        </div>

        {isLoading ? (
          <LoadingSpinner size="lg" />
        ) : agents.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无可用的智能体，请联系管理员</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {agents.map((agent) => (
              <button
                key={agent.id}
                onClick={() => handleStartChat(agent)}
                disabled={creating === agent.id}
                className={cn(
                  "group flex items-center gap-4 rounded-xl border bg-card p-4 text-left",
                  "transition-all hover:border-primary/50 hover:shadow-md hover:shadow-primary/5",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  creating === agent.id && "pointer-events-none opacity-60",
                )}
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                  <Bot className="h-5 w-5" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-sm">{agent.name}</h3>
                  <p className="mt-0.5 text-xs text-muted-foreground line-clamp-1">
                    {agent.agent_type === "creative" ? "AI 短视频创作顾问团" : agent.agent_type}
                  </p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground/30 opacity-0 transition-all group-hover:opacity-100 group-hover:text-primary group-hover:translate-x-0.5" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
