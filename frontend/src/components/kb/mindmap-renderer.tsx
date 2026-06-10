/**
 * 思维导图渲染器 — 基于 markmap (d3.js) 的交互式导图。
 *
 * 特性：
 * - 自动布局树状结构，支持缩放/平移/节点折叠
 * - 编辑模式（节点选择 + 浮层操作栏）
 * - 多格式导出（OPML / FreeMind / Markdown / JSON）
 * - 深色/浅色主题自适应
 */
import {
  useState, useRef, useEffect, useCallback, useMemo,
} from "react";
import { Markmap } from "markmap-view";
import { Transformer } from "markmap-lib";
import {
  GitBranch, Layers, Download, FileDown, Pencil, Trash2,
  Plus, X, ToggleLeft, ToggleRight,
} from "lucide-react";
import { API_BASE_URL, AUTH_TOKEN_KEY } from "@/lib/constants";

// ═══════════════════════════════════════════════════════════
// 类型
// ═══════════════════════════════════════════════════════════

export interface MindMapNode {
  id: string;
  text: string;
  note?: string;
  color?: string;
  children?: MindMapNode[];
}

export interface MindMap {
  title: string;
  root: MindMapNode;
  meta?: {
    created?: string;
    modified?: string;
    export_formats?: string[];
  };
}

// ═══════════════════════════════════════════════════════════
// JSON → Markdown 转换（供 markmap Transformer 使用）
// ═══════════════════════════════════════════════════════════

const transformer = new Transformer();

function nodeToMarkdown(node: MindMapNode, level: number): string {
  const indent = "  ".repeat(level);
  let line = `${indent}- ${escapeMarkdownText(node.text)}`;
  if (node.note) line += ` *(${escapeMarkdownText(node.note)})*`;
  const lines = [line];
  for (const child of node.children ?? []) {
    lines.push(nodeToMarkdown(child, level + 1));
  }
  return lines.join("\n");
}

function escapeMarkdownText(s: string): string {
  // 转义 markdown 特殊字符以免 transformer 误解析
  let escaped = "";
  for (const ch of s) {
    if ("*_`[]()#+-.!|{}<>~".includes(ch)) escaped += `\\${ch}`;
    else escaped += ch;
  }
  return escaped;
}

function mindmapToMarkdown(data: MindMap): string {
  const header = `# ${escapeMarkdownText(data.title)}`;
  const body = nodeToMarkdown(data.root, 0);
  return `${header}\n\n${body}`;
}

// ═══════════════════════════════════════════════════════════
// 配色 — 从枝叶到根渐深
// ═══════════════════════════════════════════════════════════

const LIGHT_PALETTE = [
  "#8b5cf6", "#6366f1", "#3b82f6", "#06b6d4",
  "#10b981", "#22c55e", "#eab308", "#f59e0b",
  "#ef4444", "#f43f5e", "#d946ef", "#a855f7",
];

const DARK_PALETTE = [
  "#a78bfa", "#818cf8", "#60a5fa", "#22d3ee",
  "#34d399", "#4ade80", "#facc15", "#fbbf24",
  "#f87171", "#fb7185", "#e879f9", "#c084fc",
];

function isDarkMode(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.classList.contains("dark");
}

function getPalette(): string[] {
  return isDarkMode() ? DARK_PALETTE : LIGHT_PALETTE;
}

function depthColor(depth: number): string {
  const p = getPalette();
  return p[depth % p.length];
}

// ═══════════════════════════════════════════════════════════
// 统计
// ═══════════════════════════════════════════════════════════

function countNodes(node: MindMapNode): number {
  return 1 + (node.children ?? []).reduce((s, c) => s + countNodes(c), 0);
}

function calcMaxDepth(node: MindMapNode, d = 1): number {
  if (!node.children?.length) return d;
  return Math.max(...node.children.map((c) => calcMaxDepth(c, d + 1)));
}

// ═══════════════════════════════════════════════════════════
// 导出格式
// ═══════════════════════════════════════════════════════════

const EXPORT_FORMATS = [
  { value: "opml", label: "OPML (XMind)", ext: ".opml" },
  { value: "mm", label: "FreeMind (.mm)", ext: ".mm" },
  { value: "markdown", label: "Markdown (.md)", ext: ".md" },
  { value: "json", label: "JSON (.json)", ext: ".json" },
] as const;

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function clientOpml(root: MindMapNode, title: string): string {
  const walk = (n: MindMapNode, indent = 2): string => {
    const p = " ".repeat(indent);
    const t = escapeXml(n.text);
    let attrs = ` text="${t}"`;
    if (n.note) attrs += ` _note="${escapeXml(n.note)}"`;
    if (!n.children?.length) return `${p}<outline${attrs} />`;
    return `${p}<outline${attrs}>\n${n.children.map((c) => walk(c, indent + 2)).join("\n")}\n${p}</outline>`;
  };
  return `<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">\n  <head><title>${escapeXml(title)}</title></head>\n  <body>\n${walk(root)}\n  </body>\n</opml>`;
}

function clientFreemind(root: MindMapNode): string {
  const walk = (n: MindMapNode, indent = 2): string => {
    const p = " ".repeat(indent);
    const t = escapeXml(n.text);
    let attrs = ` TEXT="${t}"`;
    if (n.note) attrs += ` NOTE="${escapeXml(n.note)}"`;
    if (!n.children?.length) return `${p}<node${attrs} />`;
    return `${p}<node${attrs}>\n${n.children!.map((c) => walk(c, indent + 2)).join("\n")}\n${p}</node>`;
  };
  return `<map version="1.0.1">\n${walk(root)}\n</map>`;
}

function clientMarkdown(data: MindMap): string {
  return `# ${data.title}\n\n${data.root.children?.map((c) => nodeToMarkdown(c, 0)).join("\n") ?? ""}`;
}
// ═══════════════════════════════════════════════════════════
// 编辑弹窗
// ═══════════════════════════════════════════════════════════

function EditModal({
  node,
  onSave,
  onClose,
}: {
  node: MindMapNode;
  onSave: (nodeId: string, text: string, note: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(node.text);
  const [note, setNote] = useState(node.note ?? "");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border bg-card p-5 shadow-2xl animate-scale-in">
        <h3 className="text-sm font-semibold mb-4">编辑节点</h3>
        <label className="block mb-1 text-xs text-muted-foreground">节点文本</label>
        <input
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { onSave(node.id, text.trim(), note.trim()); onClose(); } }}
          className="w-full rounded-lg border px-3 py-2 text-sm mb-3"
        />
        <label className="block mb-1 text-xs text-muted-foreground">备注（可选）</label>
        <textarea
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="w-full rounded-lg border px-3 py-2 text-sm mb-4 resize-none"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-3 py-1.5 text-xs hover:bg-muted">取消</button>
          <button
            onClick={() => { if (text.trim()) { onSave(node.id, text.trim(), note.trim()); onClose(); } }}
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs text-white hover:bg-violet-700"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════

export function MindMapRenderer({
  data,
  onSendMessage,
}: {
  data: MindMap;
  onSendMessage?: (command: string) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const mmRef = useRef<Markmap | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [editMode, setEditMode] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [editNode, setEditNode] = useState<MindMapNode | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  // 统计
  const stats = useMemo(() => ({
    nodes: countNodes(data.root),
    maxDepth: calcMaxDepth(data.root),
  }), [data]);

  // ── markmap 渲染 ──────────────────────────────────────
  useEffect(() => {
    if (!svgRef.current) return;

    const markdown = mindmapToMarkdown(data);
    const { root } = transformer.transform(markdown);

    if (mmRef.current) {
      // 增量更新
      mmRef.current.setData(root);
      void mmRef.current.fit();
    } else {
      const mm = Markmap.create(
        svgRef.current,
        {
          autoFit: true,
          duration: 400,
          initialExpandLevel: 99,  // 动态：全部展开，用户自行折叠
          maxInitialScale: 1.5,
          pan: true,
          zoom: true,
          toggleRecursively: false,
          color: (node) => {
            const d = (node.state as { depth?: number }).depth ?? 0;
            return depthColor(d);
          },
          paddingX: 20,
          spacingHorizontal: 110,
          spacingVertical: 14,
          nodeMinHeight: 32,
        },
        root,
      );
      mmRef.current = mm;
    }
  }, [data]);

  // 主题变化时重建（颜色函数依赖主题）
  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (!mmRef.current || !svgRef.current) return;
      const markdown = mindmapToMarkdown(data);
      const { root } = transformer.transform(markdown);
      mmRef.current.setData(root);
      void mmRef.current.fit();
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, [data]);

  // 销毁
  useEffect(() => {
    return () => {
      mmRef.current?.destroy();
      mmRef.current = null;
    };
  }, []);

  // ── 节点选择（编辑模式下的 SVG 点击） ────────────────
  const handleSvgClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!editMode) return;
      const target = e.target as SVGElement;
      // 向上查找所属的 <g> 节点组
      let g = target.closest("g");
      while (g) {
        const depthAttr = g.getAttribute("data-depth");
        if (depthAttr !== null) {
          const nodeId = g.getAttribute("data-id");
          if (nodeId) {
            setSelectedNodeId((prev) => (prev === nodeId ? null : nodeId));
          }
          return;
        }
        g = g.parentElement?.closest("g") ?? null;
      }
      // 点击空白区域取消选择
      setSelectedNodeId(null);
    },
    [editMode],
  );

  // ── 节点查找 ──────────────────────────────────────────
  const findNodeById = useCallback(
    (nodeId: string, node: MindMapNode = data.root): MindMapNode | null => {
      if (node.id === nodeId) return node;
      for (const child of node.children ?? []) {
        const found = findNodeById(nodeId, child);
        if (found) return found;
      }
      return null;
    },
    [data.root],
  );

  const selectedNode = selectedNodeId ? findNodeById(selectedNodeId) : null;

  // ── 编辑操作 ──────────────────────────────────────────
  const handleEdit = () => {
    if (selectedNode) setEditNode(selectedNode);
  };

  const handleEditSave = (nodeId: string, text: string, note: string) => {
    onSendMessage?.(`edit mindmap: update node ${nodeId} to "${text}"${note ? ` (备注: ${note})` : ""}`);
    setEditMode(false);
    setSelectedNodeId(null);
  };

  const handleAddChild = () => {
    if (!selectedNodeId) return;
    onSendMessage?.(`edit mindmap: add child node to ${selectedNodeId}`);
    setEditMode(false);
    setSelectedNodeId(null);
  };

  const handleDelete = () => {
    if (!selectedNode || selectedNode.id === "n0") return;
    onSendMessage?.(`edit mindmap: delete node ${selectedNode.id} (当前文本: "${selectedNode.text}")`);
    setEditMode(false);
    setSelectedNodeId(null);
  };

  // ── 导出 ──────────────────────────────────────────────
  const handleExport = useCallback(async (format: string) => {
    setExporting(true);
    const safeName = data.title.replace(/[^a-zA-Z0-9一-龥]/g, "_").replace(/_{2,}/g, "_") || "mindmap";

    try {
      const resp = await fetch(`${API_BASE_URL}/conversations/export-mindmap`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem(AUTH_TOKEN_KEY)}`,
        },
        body: JSON.stringify({ mindmap_json: data, format }),
      });
      const result = await resp.json();
      if (result.success && result.download_url) {
        // 用 <a> 标签触发下载，避免 popup 拦截
        const a = document.createElement("a");
        a.href = result.download_url;
        a.download = result.filename ?? `${safeName}${EXPORT_FORMATS.find((f) => f.value === format)?.ext ?? ""}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } else {
        throw new Error(result.error ?? "导出失败");
      }
    } catch {
      // 服务端导出失败 → 客户端降级导出
      let content: string;
      let mime: string;
      let ext: string;
      switch (format) {
        case "opml": content = clientOpml(data.root, data.title); mime = "text/xml"; ext = ".opml"; break;
        case "mm": content = clientFreemind(data.root); mime = "text/xml"; ext = ".mm"; break;
        case "markdown": content = clientMarkdown(data); mime = "text/markdown"; ext = ".md"; break;
        default: content = JSON.stringify({ ...data, _exported_at: new Date().toISOString() }, null, 2); mime = "application/json"; ext = ".json";
      }
      const blob = new Blob([content], { type: `${mime};charset=utf-8` });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${safeName}${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      setExporting(false);
      setExportOpen(false);
    }
  }, [data]);

  // ── 键盘 ──────────────────────────────────────────────
  useEffect(() => {
    if (!editMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSelectedNodeId(null); setEditMode(false); }
      if (e.key === "Enter" && selectedNodeId) { e.preventDefault(); handleEdit(); }
      if (e.key === "Delete" && selectedNodeId && selectedNode?.id !== "n0") { handleDelete(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editMode, selectedNodeId, selectedNode]);

  return (
    <div ref={containerRef} className="mindmap-canvas my-3 rounded-xl border bg-card/60 overflow-hidden select-none">
      {/* ── 工具栏 ─────────────────────────────── */}
      <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b bg-muted/30">
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch className="h-4 w-4 shrink-0 text-violet-500" />
          <h4 className="text-sm font-semibold truncate">{data.title}</h4>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* 统计 */}
          <span className="text-[10px] text-muted-foreground flex items-center gap-1">
            <Layers className="h-3 w-3" />
            {stats.nodes} 节点 · {stats.maxDepth} 层
          </span>

          {/* 编辑模式开关 */}
          <button
            type="button"
            onClick={() => { setEditMode(!editMode); setSelectedNodeId(null); }}
            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors ${
              editMode
                ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
            title={editMode ? "退出编辑模式" : "进入编辑模式（可点击选择节点进行编辑）"}
          >
            {editMode ? <ToggleRight className="h-3.5 w-3.5" /> : <ToggleLeft className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">编辑</span>
          </button>

          {/* 导出 */}
          <div className="relative">
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs
                         bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300
                         hover:bg-violet-200 dark:hover:bg-violet-900/50 transition-colors"
              onClick={() => setExportOpen(!exportOpen)}
              disabled={exporting}
            >
              <Download className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">导出</span>
            </button>
            {exportOpen && (
              <div className="absolute right-0 top-full mt-1 z-30 bg-card border rounded-lg shadow-lg py-1 min-w-[160px]">
                {EXPORT_FORMATS.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted flex items-center gap-2"
                    onClick={() => handleExport(f.value)}
                  >
                    <FileDown className="h-3 w-3 text-muted-foreground" />
                    {f.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── 编辑模式操作栏 ─────────────────────── */}
      {editMode && selectedNode && (
        <div className="flex items-center gap-1 px-4 py-2 border-b bg-amber-50/50 dark:bg-amber-950/20 animate-slide-in-down">
          <span className="text-xs text-muted-foreground mr-2 truncate max-w-[200px]">
            已选择: <strong className="text-foreground">{selectedNode.text}</strong>
          </span>
          <div className="flex items-center gap-1 ml-auto">
            <button
              onClick={handleEdit}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs bg-white dark:bg-zinc-800 border hover:bg-muted transition-colors"
            >
              <Pencil className="h-3 w-3" /> 编辑
            </button>
            <button
              onClick={handleAddChild}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs bg-white dark:bg-zinc-800 border hover:bg-muted transition-colors"
            >
              <Plus className="h-3 w-3" /> 子节点
            </button>
            {selectedNode.id !== "n0" && (
              <button
                onClick={handleDelete}
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs bg-white dark:bg-zinc-800 border border-red-200 dark:border-red-900 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
              >
                <Trash2 className="h-3 w-3" /> 删除
              </button>
            )}
            <button
              onClick={() => setSelectedNodeId(null)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        </div>
      )}

      {/* ── 编辑模式指示条 ─────────────────────── */}
      {editMode && !selectedNode && (
        <div className="flex items-center gap-2 px-4 py-1.5 border-b bg-amber-50/30 dark:bg-amber-950/10 text-[11px] text-muted-foreground">
          <ToggleRight className="h-3 w-3 text-amber-500" />
          编辑模式已开启 — 点击节点可选中编辑，Esc 退出编辑模式
        </div>
      )}

      {/* ── SVG 画布 ───────────────────────────── */}
      <div className="relative" style={{ height: Math.min(Math.max(stats.nodes * 40, 380), 700) }}>
        <svg
          ref={svgRef}
          className="w-full h-full cursor-grab active:cursor-grabbing"
          style={{ background: "transparent" }}
          onClick={handleSvgClick}
        />
      </div>

      {/* ── 底部提示 ───────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-1.5 border-t bg-muted/20 text-[10px] text-muted-foreground/60">
        <span>🖱️ 滚轮缩放 · 拖拽平移 · 点击折叠/展开</span>
        {data.meta?.created && (
          <span>创建于 {new Date(data.meta.created).toLocaleDateString("zh-CN")}</span>
        )}
      </div>

      {/* ── 编辑弹窗 ───────────────────────────── */}
      {editNode && (
        <EditModal
          node={editNode}
          onSave={handleEditSave}
          onClose={() => setEditNode(null)}
        />
      )}
    </div>
  );
}

// 工具函数移至 mindmap-utils.ts，请从该文件导入。
