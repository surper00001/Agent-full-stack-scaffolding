import { useState } from "react";
import {
  Wrench, Check, Loader2, AlertCircle, ChevronDown, Search,
  Code2, FileText, Globe, Database, Image, ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolCall } from "@/types";

interface ToolCallRendererProps {
  toolCall: ToolCall;
}

/** 工具图标映射 */
function getToolIcon(name: string) {
  if (name.includes("search") || name.includes("knowledge")) return Search;
  if (name.includes("code") || name.includes("python") || name.includes("execute")) return Code2;
  if (name.includes("file") || name.includes("save") || name.includes("write") || name.includes("read")) return FileText;
  if (name.includes("web") || name.includes("http") || name.includes("fetch") || name.includes("url")) return Globe;
  if (name.includes("db") || name.includes("sql") || name.includes("query")) return Database;
  if (name.includes("image") || name.includes("vision") || name.includes("ocr")) return Image;
  return Wrench;
}

/** 工具名中文映射 */
function getToolLabel(name: string): string {
  const labels: Record<string, string> = {
    search_knowledge_base: "知识库检索",
    web_search: "网络搜索",
    code_execution: "代码执行",
    python_execute: "Python 执行",
    save_markdown_file: "保存 Markdown",
    save_text_file: "保存文本",
    read_file: "读取文件",
    tool_search: "工具搜索",
    image_analysis: "图片分析",
    calculate: "数学计算",
    web_fetch: "网页抓取",
  };
  return labels[name] ?? name;
}

/** render result based on tool type */
function renderResult(name: string, result: unknown) {
  const resultStr = typeof result === "string" ? result : JSON.stringify(result, null, 2);

  // KB search -> show citations
  if (name === "search_knowledge_base") {
    try {
      const parsed = typeof result === "string" ? JSON.parse(result) : result;
      if (parsed && typeof parsed === "object") {
        const totalFound = (parsed as Record<string, unknown>).total_found ?? 0;
        const results = (parsed as Record<string, unknown>).results as Array<Record<string, unknown>> | undefined;
        return (
          <div className="text-[11px] space-y-1.5">
            <p className="text-muted-foreground">
              找到 <span className="font-medium text-foreground">{totalFound}</span> 条结果
              {results && <span>，返回前 {results.length} 条</span>}
            </p>
            {results && results.slice(0, 3).map((r, i) => (
              <div key={i} className="bg-muted/30 rounded px-2 py-1">
                <p className="text-[10px] text-muted-foreground truncate">
                  {(r.source as string) || (r.document_id as string) || `结果 ${i + 1}`}
                </p>
                <p className="text-[11px] leading-relaxed line-clamp-2">
                  {(r.content as string)?.substring(0, 200)}
                </p>
              </div>
            ))}
          </div>
        );
      }
    } catch { /* ignore parse errors */ }
  }

  // Code execution -> show code + output
  if (name.includes("code") || name.includes("python") || name.includes("execute")) {
    try {
      const parsed = typeof result === "string" ? JSON.parse(result) : result;
      if (parsed && typeof parsed === "object") {
        const code = (parsed as Record<string, unknown>).code || (parsed as Record<string, unknown>).script;
        const output = (parsed as Record<string, unknown>).output || (parsed as Record<string, unknown>).stdout;
        const error = (parsed as Record<string, unknown>).error || (parsed as Record<string, unknown>).stderr;
        return (
          <div className="space-y-2">
            {code && (
              <div>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">代码</span>
                <pre className="mt-0.5 bg-muted/50 px-2 py-1 rounded text-[10px] font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  {String(code).substring(0, 500)}
                </pre>
              </div>
            )}
            {output && (
              <div>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">输出</span>
                <pre className="mt-0.5 bg-muted/50 px-2 py-1 rounded text-[10px] font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  {String(output).substring(0, 500)}
                </pre>
              </div>
            )}
            {error && (
              <div>
                <span className="text-[10px] text-red-500 uppercase tracking-wider">错误</span>
                <pre className="mt-0.5 bg-red-50 dark:bg-red-950/20 px-2 py-1 rounded text-[10px] font-mono text-red-600 dark:text-red-400 max-h-32 overflow-y-auto">
                  {String(error).substring(0, 300)}
                </pre>
              </div>
            )}
          </div>
        );
      }
    } catch { /* ignore parse errors */ }
  }

  // Web search -> show links
  if (name.includes("web") || name.includes("search")) {
    try {
      const parsed = typeof result === "string" ? JSON.parse(result) : result;
      if (Array.isArray(parsed)) {
        return (
          <div className="space-y-1">
            {parsed.slice(0, 5).map((item: Record<string, unknown>, i: number) => (
              <a
                key={i}
                href={item.url as string}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-[11px] text-blue-600 dark:text-blue-400 hover:underline"
              >
                <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                <span className="truncate">{(item.title || item.url || `结果 ${i + 1}`) as string}</span>
              </a>
            ))}
          </div>
        );
      }
      if (parsed && typeof parsed === "object" && (parsed as Record<string, unknown>).results) {
        const results = (parsed as Record<string, unknown>).results as Array<Record<string, unknown>>;
        return (
          <div className="space-y-1">
            {results.slice(0, 5).map((item: Record<string, unknown>, i: number) => (
              <a
                key={i}
                href={item.url as string}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-[11px] text-blue-600 dark:text-blue-400 hover:underline"
              >
                <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                <span className="truncate">{(item.title || item.url || `结果 ${i + 1}`) as string}</span>
              </a>
            ))}
          </div>
        );
      }
    } catch { /* ignore parse errors */ }
  }

  // File operations -> show path info
  if (name.includes("file") || name.includes("save") || name.includes("read") || name.includes("write")) {
    return (
      <div className="text-[11px] text-muted-foreground leading-relaxed max-h-32 overflow-y-auto">
        {resultStr.substring(0, 500)}
      </div>
    );
  }

  // Default: plain text (truncated)
  return (
    <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap max-h-32 overflow-y-auto leading-relaxed">
      {resultStr.substring(0, 500)}
    </pre>
  );
}

/** render arguments based on tool type */
function renderArguments(name: string, args: Record<string, unknown>) {
  const entries = Object.entries(args);

  // Show as key-value tags for readability
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([key, value]) => {
        const valStr = typeof value === "string" ? value : JSON.stringify(value);
        const displayVal = valStr.length > 80 ? valStr.substring(0, 80) + "..." : valStr;
        return (
          <span key={key} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted/50 text-[10px]">
            <span className="text-muted-foreground">{key}</span>
            <span className="font-mono text-foreground/70">=</span>
            <span className="font-mono">{displayVal}</span>
          </span>
        );
      })}
    </div>
  );
}

export function ToolCallRenderer({ toolCall }: ToolCallRendererProps) {
  const [isOpen, setIsOpen] = useState(false);
  const Icon = getToolIcon(toolCall.name);
  const label = getToolLabel(toolCall.name);

  return (
    <div
      className={cn(
        "rounded-lg border text-xs group my-1.5 overflow-hidden transition-colors",
        toolCall.status === "running" && "border-blue-200 bg-blue-50/30 dark:border-blue-800 dark:bg-blue-950/20",
        toolCall.status === "completed" && "border-emerald-200 bg-emerald-50/20 dark:border-emerald-800 dark:bg-emerald-950/10",
        toolCall.status === "error" && "border-red-200 bg-red-50/30 dark:border-red-800 dark:bg-red-950/20",
      )}
    >
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 w-full text-left hover:bg-muted/30 transition-colors"
      >
        {/* Status indicator */}
        <span className={cn(
          "h-2 w-2 rounded-full shrink-0",
          toolCall.status === "running" && "bg-blue-500 animate-pulse",
          toolCall.status === "completed" && "bg-emerald-500",
          toolCall.status === "error" && "bg-red-500",
        )} />

        <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />

        <span className="font-medium text-[11px] truncate">
          {label}
        </span>

        {toolCall.status === "running" && (
          <span className="text-[10px] text-blue-600 dark:text-blue-400 flex items-center gap-1">
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
            执行中
          </span>
        )}
        {toolCall.status === "completed" && (
          <Check className="h-3 w-3 text-emerald-500 ml-auto shrink-0" />
        )}
        {toolCall.status === "error" && (
          <AlertCircle className="h-3 w-3 text-red-500 ml-auto shrink-0" />
        )}

        <ChevronDown
          className={cn(
            "h-3 w-3 text-muted-foreground transition-transform duration-200 shrink-0",
            isOpen && "rotate-180"
          )}
        />
      </button>

      {/* Expanded content */}
      {isOpen && (
        <div className="px-3 py-2 border-t space-y-2 bg-background/30">
          {/* Arguments */}
          {toolCall.arguments && Object.keys(toolCall.arguments).length > 0 && (
            <div>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">参数</span>
              <div className="mt-0.5">
                {renderArguments(toolCall.name, toolCall.arguments)}
              </div>
            </div>
          )}

          {/* Result */}
          {toolCall.result !== undefined && toolCall.status !== "running" && (
            <div>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">结果</span>
              <div className="mt-0.5">
                {renderResult(toolCall.name, toolCall.result)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
