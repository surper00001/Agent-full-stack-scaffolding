import { useState, useRef, useEffect, type FormEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { useStreamMessage } from "@/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Send, Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";

interface LocalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

/**
 * 对话详情页
 * 支持流式对话 — 发送消息后实时展示Agent流式响应
 */
export default function ConversationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { isStreaming, streamContent, sendMessage } = useStreamMessage();
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, streamContent]);

  const handleSend = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming || !id) return;

    const userMessage: LocalMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    try {
      const response = await sendMessage(id, userMessage.content);
      const assistantMessage: LocalMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      const errorMessage: LocalMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `错误: ${(err as Error).message}`,
      };
      setMessages((prev) => [...prev, errorMessage]);
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      {/* 顶部导航 */}
      <div className="flex items-center gap-4 border-b pb-4">
        <Link to="/conversations">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <h1 className="text-xl font-bold">对话</h1>
      </div>

      {/* 消息列表 */}
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto py-4"
      >
        {messages.length === 0 && !isStreaming && (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <p>发送第一条消息开始对话</p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* 流式输出中的消息 */}
        {isStreaming && streamContent && (
          <MessageBubble
            message={{
              id: "streaming",
              role: "assistant",
              content: streamContent,
            }}
            isStreaming
          />
        )}
        {isStreaming && !streamContent && (
          <div className="flex items-center gap-2 px-4">
            <Bot className="h-4 w-4" />
            <span className="text-sm text-muted-foreground">思考中...</span>
          </div>
        )}
      </div>

      {/* 输入区域 */}
      <form onSubmit={handleSend} className="flex gap-3 border-t pt-4">
        <Input
          placeholder="输入消息..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isStreaming}
          className="flex-1"
        />
        <Button type="submit" disabled={!input.trim() || isStreaming}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}

/** 消息气泡组件 */
function MessageBubble({
  message,
  isStreaming,
}: {
  message: LocalMessage;
  isStreaming?: boolean;
}) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex gap-3 px-4", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted",
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : (
          <Bot className="h-4 w-4" />
        )}
      </div>
      <div
        className={cn(
          "max-w-[75%] rounded-lg px-4 py-2 text-sm",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted",
          isStreaming && "border border-dashed border-primary/30",
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
      </div>
    </div>
  );
}
