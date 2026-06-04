/**
 * SafeMarkdown — 安全的 Markdown 渲染组件。
 *
 * 使用 react-markdown + rehype-sanitize + remark-gfm，
 * 替代所有 dangerouslySetInnerHTML 的简易 Markdown 实现，
 * 消除 XSS 攻击面。
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";

interface SafeMarkdownProps {
  /** Markdown 文本 */
  children: string;
  /** 附加的 CSS 类名 */
  className?: string;
}

/** 全局共享的组件映射（保持渲染一致性） */
const markdownComponents = {
  pre: ({ children, ...props }: React.ComponentPropsWithoutRef<"pre">) => (
    <pre
      className="bg-zinc-950 text-zinc-200 rounded-lg p-4 my-3 overflow-x-auto text-xs leading-relaxed"
      {...props}
    >
      {children}
    </pre>
  ),
  code: ({
    className: cls,
    children,
    ...props
  }: React.ComponentPropsWithoutRef<"code"> & { className?: string }) => {
    const isInline = !cls?.includes("language-") || cls === undefined;
    return isInline ? (
      <code
        className="bg-muted px-1.5 py-0.5 rounded text-[13px] font-mono"
        {...props}
      >
        {children}
      </code>
    ) : (
      <code className={cls} {...props}>
        {children}
      </code>
    );
  },
  h1: ({ children, ...props }: React.ComponentPropsWithoutRef<"h1">) => (
    <h1 className="text-xl font-bold mt-6 mb-3" {...props}>{children}</h1>
  ),
  h2: ({ children, ...props }: React.ComponentPropsWithoutRef<"h2">) => (
    <h2 className="text-lg font-semibold mt-5 mb-2" {...props}>{children}</h2>
  ),
  h3: ({ children, ...props }: React.ComponentPropsWithoutRef<"h3">) => (
    <h3 className="text-base font-semibold mt-4 mb-2" {...props}>{children}</h3>
  ),
  ul: ({ children, ...props }: React.ComponentPropsWithoutRef<"ul">) => (
    <ul className="list-disc ml-4 space-y-1" {...props}>{children}</ul>
  ),
  ol: ({ children, ...props }: React.ComponentPropsWithoutRef<"ol">) => (
    <ol className="list-decimal ml-4 space-y-1" {...props}>{children}</ol>
  ),
  table: ({ children, ...props }: React.ComponentPropsWithoutRef<"table">) => (
    <div className="overflow-x-auto my-3">
      <table className="w-full border-collapse text-xs" {...props}>{children}</table>
    </div>
  ),
  th: ({ children, ...props }: React.ComponentPropsWithoutRef<"th">) => (
    <th className="border px-2 py-1 bg-muted/50 font-medium text-left" {...props}>{children}</th>
  ),
  td: ({ children, ...props }: React.ComponentPropsWithoutRef<"td">) => (
    <td className="border px-2 py-1" {...props}>{children}</td>
  ),
};

export function SafeMarkdown({ children, className }: SafeMarkdownProps) {
  return (
    <span className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={markdownComponents}
      >
        {children}
      </ReactMarkdown>
    </span>
  );
}
