import { useState } from "react";
import { Brain, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StreamTiming } from "@/types";

interface ThinkingCardProps {
  content: string;
  timing?: StreamTiming;
  defaultOpen?: boolean;
}

export function ThinkingCard({ content, timing, defaultOpen = true }: ThinkingCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 dark:border-amber-800 dark:bg-amber-950/30 my-2 overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-amber-100/50 dark:hover:bg-amber-900/30 transition-colors"
      >
        <Brain className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
        <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
          思考过程
        </span>
        {timing && (
          <span className="text-[10px] text-amber-500 ml-1 tabular-nums">
            {(timing.elapsed_ms / 1000).toFixed(1)}s
          </span>
        )}
        <ChevronDown
          className={cn(
            "h-3 w-3 text-amber-500 ml-auto transition-transform duration-200",
            isOpen && "rotate-180"
          )}
        />
      </button>
      {isOpen && (
        <div className="px-3 py-2 border-t border-amber-200 dark:border-amber-800 bg-white/50 dark:bg-black/20">
          <p className="text-xs text-amber-900 dark:text-amber-200 leading-relaxed whitespace-pre-wrap">
            {content}
          </p>
        </div>
      )}
    </div>
  );
}
