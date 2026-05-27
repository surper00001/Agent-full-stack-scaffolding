/**
 * 思维导图工具函数 — 从消息中提取导图数据。
 */
import type { MindMap } from "./mindmap-renderer";

/** 从助手消息 metadata 中提取 mindmap JSON。返回 null 表示不含导图。 */
export function extractMindmapFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): MindMap | null {
  if (!metadata?.mindmap) return null;
  const mm = metadata.mindmap;
  if (typeof mm === "object" && mm !== null && "root" in (mm as object)) {
    return mm as MindMap;
  }
  return null;
}

/** 从消息文本末尾的 ```json 代码块解析思维导图 JSON。 */
export function parseMindmapFromContent(content: string): MindMap | null {
  const blocks = content.match(/```json\s*([\s\S]*?)\s*```/g);
  if (!blocks) return null;

  for (let i = blocks.length - 1; i >= 0; i--) {
    try {
      const json = blocks[i].replace(/```json\s*/, "").replace(/\s*```$/, "");
      const parsed = JSON.parse(json);
      if (
        parsed &&
        typeof parsed === "object" &&
        !Array.isArray(parsed) &&
        parsed.root &&
        typeof parsed.root === "object" &&
        parsed.root.text &&
        Array.isArray(parsed.root.children) &&
        parsed.root.children.length > 0
      ) {
        return parsed as MindMap;
      }
    } catch { /* continue */ }
  }
  return null;
}
