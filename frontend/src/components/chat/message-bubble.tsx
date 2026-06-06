/**
 * MessageBubble — 聊天消息气泡组件。
 *
 * 从 ChatDetailPage 提取，减少父组件复杂度。
 * 支持：用户/助手/系统消息、引用卡片、思维导图、文件下载、工具调用。
 */
import { memo, useState } from "react";
import { Bot, User, Copy, Check, Download, Wrench, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { SafeMarkdown } from "@/components/common/safe-markdown";
import { CitationCards, type KBCitation } from "@/components/kb/citation-cards";
import { InlineImageMessage } from "@/components/kb/inline-image-message";
import { MindMapRenderer, type MindMap } from "@/components/kb/mindmap-renderer";
import type { ToolCall } from "@/types";

export interface FileOutput {
  filename: string;
  download_url: string;
  label: string;
  mime_type?: string;
  size_display?: string;
}

export interface LocalMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  tool_calls?: ToolCall[];
  files?: FileOutput[];
  citations?: KBCitation[];
  mindmap?: MindMap;
}

interface MessageBubbleProps {
  message: LocalMessage;
  /** 是否显示时间戳格式化字符串 */
  showTime?: string | null;
  /** KB 引用 ID */
  kbId?: string;
  /** 文档 ID（用于图片渲染） */
  docId?: string;
  /** 流式输出中 — 显示闪烁光标 */
  isStreaming?: boolean;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="ml-auto shrink-0 rounded-md p-1.5 text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors"
      title="复制消息"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function ToolCallsDisplay({ calls }: { calls: ToolCall[] }) {
  return (
    <div className="mt-2 space-y-1.5 border-l-2 border-muted pl-3">
      {calls.map((tc) => (
        <div key={tc.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Wrench className="h-3 w-3 shrink-0" />
          <span className="font-medium">{tc.name}</span>
          {tc.status === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
        </div>
      ))}
    </div>
  );
}

function FileOutputs({ files }: { files: FileOutput[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {files.map((f) => (
        <a
          key={f.filename}
          href={f.download_url}
          download
          className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-muted transition-colors"
        >
          <Download className="h-3 w-3" />
          <span>{f.label || f.filename}</span>
          {f.size_display && <span className="text-muted-foreground">({f.size_display})</span>}
        </a>
      ))}
    </div>
  );
}

export const MessageBubble = memo(function MessageBubble({
  message,
  showTime,
  kbId = "",
  docId = "",
  isStreaming,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  // 系统消息 — 居中显示
  if (message.role === "system") {
    return (
      <div className="flex justify-center px-4 py-2">
        <span className="text-xs text-destructive/70 bg-destructive/[0.04] rounded-full px-3 py-1">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group flex gap-3",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-medium",
          isUser
            ? "bg-primary/10 border-primary/20 text-primary"
            : "bg-muted border-border text-muted-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Body */}
      <div className={cn("flex max-w-[80%] flex-col gap-1", isUser && "items-end")}>
        {/* Time */}
        {showTime && (
          <span className="text-[10px] text-muted-foreground/60 px-1">
            {showTime}
          </span>
        )}

        {/* Content */}
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground rounded-tr-md"
              : "bg-muted/60 border rounded-tl-md",
            isStreaming && "streaming-cursor border-dashed border-foreground/10",
          )}
        >
          {isUser ? (
            <span className="whitespace-pre-wrap">{message.content}</span>
          ) : (
            <SafeMarkdown>{message.content}</SafeMarkdown>
          )}

          {/* Tool calls */}
          {message.tool_calls && message.tool_calls.length > 0 && (
            <ToolCallsDisplay calls={message.tool_calls} />
          )}

          {/* File outputs */}
          {message.files && message.files.length > 0 && (
            <FileOutputs files={message.files} />
          )}

          {/* Copy button */}
          {!isUser && message.content && (
            <div className="mt-2 flex items-center justify-end opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton text={message.content} />
            </div>
          )}
        </div>

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <CitationCards citations={message.citations} />
        )}

        {/* Inline images (KB references) */}
        {message.citations?.map(
          (cite, i) =>
            cite.image_url && (
              <InlineImageMessage
                key={`img-${i}`}
                cite={cite}
                citeNum={i + 1}
                kbId={kbId}
                docId={docId}
              />
            ),
        )}

        {/* Mind map */}
        {message.mindmap && (
          <div className="w-full mt-2">
            <MindMapRenderer mindmap={message.mindmap} />
          </div>
        )}
      </div>
    </div>
  );
});
