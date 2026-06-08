import { useState, useEffect, useRef, useCallback } from "react";
import { Search, X, MessageSquare, FileText, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import client from "@/api/client";

interface SearchResult {
  conversation_id: string;
  title: string;
  match_type: "title" | "message";
  preview: string;
  role: string | null;
  created_at: string | null;
}

interface GlobalSearchProps {
  open: boolean;
  onClose: () => void;
}

export function GlobalSearch({ open, onClose }: GlobalSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await client.get("/conversations/search", {
          params: { q: query, limit: 10 },
        });
        setResults(data.data?.results || []);
        setSelectedIdx(0);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && results[selectedIdx]) {
        navigate(`/chat/${results[selectedIdx].conversation_id}`);
        onClose();
      } else if (e.key === "Escape") {
        onClose();
      }
    },
    [results, selectedIdx, navigate, onClose],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="relative z-50 w-full max-w-xl bg-background rounded-xl border shadow-2xl overflow-hidden">
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b">
          {loading ? (
            <Loader2 className="h-4 w-4 text-muted-foreground animate-spin shrink-0" />
          ) : (
            <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          )}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索对话内容... (Ctrl+K)"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Results */}
        {results.length > 0 && (
          <div className="max-h-80 overflow-y-auto p-2">
            {results.map((r, i) => (
              <button
                key={r.conversation_id + i}
                onClick={() => { navigate(`/chat/${r.conversation_id}`); onClose(); }}
                className={cn(
                  "w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors",
                  i === selectedIdx ? "bg-accent" : "hover:bg-muted/50",
                )}
              >
                {r.match_type === "title" ? (
                  <FileText className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                ) : (
                  <MessageSquare className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{r.title}</p>
                  <p className="text-[11px] text-muted-foreground truncate">{r.preview}</p>
                  {r.match_type === "message" && r.role && (
                    <span className="text-[10px] text-muted-foreground mt-0.5 inline-block">
                      {r.role === "user" ? "用户" : r.role === "assistant" ? "AI" : r.role} 消息
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}

        {query && !loading && results.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            未找到匹配的对话
          </div>
        )}

        {!query && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            输入关键词搜索对话标题和内容
          </div>
        )}
      </div>
    </div>
  );
}
