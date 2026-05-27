"""L2 创作工具 — 思维导图生成、编辑、导出与 URL 导入。"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from langchain_core.tools import tool
from loguru import logger

from src.core.config import get_settings

# ── 导出临时目录 ──────────────────────────────────────
_EXPORT_DIR = Path(get_settings().file_output_dir) / "mindmap_exports"
_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════
# ID 规范化
# ═══════════════════════════════════════════════════════

def normalize_node_ids(
    node: dict[str, Any],
    parent_prefix: str = "n0",
) -> dict[str, Any]:
    """递归修复所有节点的 id，确保符合 n0 / n1 / n2-0 规范。"""
    node["id"] = parent_prefix
    children = node.get("children", [])
    if children:
        for i, child in enumerate(children):
            if parent_prefix == "n0":
                # 一级节点: n1, n2, n3...
                child_prefix = f"n{i + 1}"
            else:
                # 二级+节点: n1-0, n1-1, n2-0...
                child_prefix = f"{parent_prefix}-{i}"
            normalize_node_ids(child, child_prefix)
    return node


def validate_mindmap(mindmap: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化思维导图 JSON。"""
    if "title" not in mindmap:
        mindmap["title"] = "未命名导图"
    if "root" not in mindmap:
        return {"error": "缺少 root 根节点", "mindmap": mindmap}
    root = mindmap["root"]
    if "id" not in root:
        root["id"] = "n0"
    if root["id"] != "n0":
        root["id"] = "n0"
    if "text" not in root:
        root["text"] = mindmap.get("title", "根节点")
    root.setdefault("children", [])
    normalize_node_ids(root)
    return mindmap


def count_nodes(node: dict[str, Any]) -> int:
    """递归统计节点数。"""
    return 1 + sum(count_nodes(c) for c in node.get("children", []))


def max_depth(node: dict[str, Any], current: int = 1) -> int:
    """递归计算最大深度。"""
    children = node.get("children", [])
    if not children:
        return current
    return max(max_depth(c, current + 1) for c in children)


def find_node(node: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    """在树中查找节点。"""
    if node.get("id") == node_id:
        return node
    for child in node.get("children", []):
        found = find_node(child, node_id)
        if found is not None:
            return found
    return None


def find_parent(root: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    """查找父节点。"""
    for child in root.get("children", []):
        if child.get("id") == node_id:
            return root
        found = find_parent(child, node_id)
        if found is not None:
            return found
    return None


# ═══════════════════════════════════════════════════════
# 工具 1: generate_mindmap
# ═══════════════════════════════════════════════════════

@tool
def generate_mindmap(
    topic: str,
    context: str = "",
) -> str:
    """
    生成思维导图的结构模板，返回带智能深度推断指令的模板。
    LLM 需要根据主题复杂度自行决定导图层级数（不要用固定深度）。

    深度推断指南（你作为 LLM 自行判断，无需遵循固定值）：
    - 简单/单一维度主题（如"今日待办"）→ 2-3 层即可，用广度覆盖而非深度
    - 中等复杂度（如"Python 基础语法"）→ 3-4 层，主要分支细分到实用级别
    - 复杂/多维度主题（如"机器学习算法体系"）→ 4-5 层，核心分支可更深
    - 分支深度不必统一：核心概念可深入，辅助分支可浅出
    - 宁可适度深挖有意义的子主题，不要为了凑层数塞废话

    Args:
        topic: 思维导图主题，如 "机器学习算法分类"
        context: 补充上下文材料（可选），如粘贴的文本或 URL 抓取的内容
    """
    return json.dumps({
        "action": "generate_mindmap",
        "topic": topic,
        "context": context[:3000] if context else "",
        "output_format": {
            "title": topic,
            "root": {
                "id": "n0",
                "text": topic,
                "note": "根节点",
                "children": [
                    {
                        "id": "nX",
                        "text": "子节点示例",
                        "note": "可选备注",
                        "children": [],
                    },
                ],
            },
        },
        "instruction": (
            f"请根据主题「{topic}」生成完整的思维导图 JSON 结构。\n\n"
            f"## 深度要求（动态，你自行判断）\n"
            f"- 评估主题复杂度：广度（并列维度数）和深度（每个维度的细分层级）\n"
            f"- 不同分支可以有不同深度，核心分支深挖、辅助分支点到为止\n"
            f"- 每个叶子节点应该是具体可操作/可理解的要点，而非空洞概括\n"
            f"- 适当使用 note 字段补充说明、定义或示例\n\n"
            f"## 输出规范\n"
            f"1. 必须是有效的 JSON，用 ```json 代码块包裹（不要用其他标记）\n"
            f"2. 根节点 id='n0'，一级子节点 id='n1','n2',...，二级='n1-1','n1-2',...\n"
            f"3. 每个节点包含 id, text，可选 note（备注说明）\n"
            f"4. 合理组织层级关系，覆盖主题的关键方面，避免冗余重复\n"
            + (f"\n5. 融入补充内容的关键信息: {context[:500]}" if context else "")
        ),
    }, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════
# 工具 2: edit_mindmap
# ═══════════════════════════════════════════════════════

@tool
def edit_mindmap(
    mindmap_json: str,
    operation: str,
    node_id: str = "",
    new_text: str = "",
    new_note: str = "",
    target_id: str = "",
    index: int = -1,
) -> str:
    """
    编辑现有的思维导图结构。支持增删改移四种操作。

    Args:
        mindmap_json: 当前的完整思维导图 JSON 字符串
        operation: 操作类型 — add | update | delete | move
        node_id: 要操作的节点 ID（move 时为待移动节点）
        new_text: 新文本内容（update/add 时使用）
        new_note: 新备注（update 时使用，可选）
        target_id: 目标父节点 ID（add/move 时的目标位置）
        index: 插入位置（add/move 时指定子节点位置，-1 表示末尾）
    """
    try:
        mindmap: dict[str, Any] = json.loads(mindmap_json)
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"无效的 JSON: {e}"}, ensure_ascii=False)

    if "root" not in mindmap:
        return json.dumps({"success": False, "error": "缺少 root 根节点"}, ensure_ascii=False)

    mindmap = copy.deepcopy(mindmap)
    new_root = mindmap["root"]

    try:
        if operation == "add":
            # 在 target_id 下添加子节点（默认根节点）
            parent = find_node(new_root, target_id) if target_id else new_root
            if parent is None:
                return json.dumps({"success": False, "error": f"未找到节点: {target_id}"}, ensure_ascii=False)

            parent.setdefault("children", [])
            new_idx = index if index >= 0 else len(parent["children"])
            child_prefix = target_id if target_id else "n"
            prefix = f"{child_prefix}-{new_idx}" if child_prefix != "n" else f"n{new_idx}"

            new_node: dict[str, Any] = {
                "id": prefix,
                "text": new_text or "新节点",
                "children": [],
            }
            if new_note:
                new_node["note"] = new_note

            if 0 <= new_idx < len(parent["children"]):
                parent["children"].insert(new_idx, new_node)
            else:
                parent["children"].append(new_node)

            result = {"success": True, "message": f"已在 {target_id or 'root'} 下添加节点 {prefix}", "mindmap_json": mindmap}

        elif operation == "update":
            target = find_node(new_root, node_id)
            if target is None:
                return json.dumps({"success": False, "error": f"未找到节点: {node_id}"}, ensure_ascii=False)

            if new_text:
                target["text"] = new_text
            if new_note is not None:
                if new_note:
                    target["note"] = new_note
                else:
                    target.pop("note", None)

            result = {"success": True, "message": f"已更新节点 {node_id}", "mindmap_json": mindmap}

        elif operation == "delete":
            if node_id == "n0":
                return json.dumps({"success": False, "error": "不能删除根节点"}, ensure_ascii=False)

            parent = find_parent(new_root, node_id)
            if parent is None:
                return json.dumps({"success": False, "error": f"未找到节点: {node_id}"}, ensure_ascii=False)

            children = parent.get("children", [])
            parent["children"] = [c for c in children if c.get("id") != node_id]
            result = {"success": True, "message": f"已删除节点 {node_id} 及其所有后代", "mindmap_json": mindmap}

        elif operation == "move":
            if node_id == "n0":
                return json.dumps({"success": False, "error": "不能移动根节点"}, ensure_ascii=False)

            source = find_node(new_root, node_id)
            if source is None:
                return json.dumps({"success": False, "error": f"未找到源节点: {node_id}"}, ensure_ascii=False)

            old_parent = find_parent(new_root, node_id)
            new_parent = find_node(new_root, target_id) if target_id else new_root
            if new_parent is None:
                return json.dumps({"success": False, "error": f"未找到目标父节点: {target_id}"}, ensure_ascii=False)

            # 防止移到自己的后代下
            def is_descendant(ancestor: dict[str, Any], descendant_id: str) -> bool:
                return find_node(ancestor, descendant_id) is not None
            if is_descendant(source, target_id):
                return json.dumps({"success": False, "error": "不能移动到自己的后代节点下"}, ensure_ascii=False)

            # 从旧父节点移除
            if old_parent is not None:
                old_children = old_parent.get("children", [])
                old_parent["children"] = [c for c in old_children if c.get("id") != node_id]

            # 添加到新父节点
            new_parent.setdefault("children", [])
            insert_idx = index if index >= 0 else len(new_parent["children"])
            if 0 <= insert_idx < len(new_parent["children"]):
                new_parent["children"].insert(insert_idx, source)
            else:
                new_parent["children"].append(source)

            result = {"success": True, "message": f"已将节点 {node_id} 移动到 {target_id or 'root'} 下", "mindmap_json": mindmap}

        else:
            return json.dumps({"success": False, "error": f"不支持的操作: {operation}，支持 add/update/delete/move"}, ensure_ascii=False)

        # 规范化 id
        if result.get("mindmap_json"):
            normalize_node_ids(result["mindmap_json"]["root"])

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"edit_mindmap 失败: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════
# 工具 3: export_mindmap
# ═══════════════════════════════════════════════════════

def _to_opml(node: dict[str, Any], indent: int = 2) -> str:
    """递归转换为 OPML outline（使用 XML 标准转义）。"""
    prefix = " " * indent
    text = xml_escape(node.get("text", ""), {'"': "&quot;"})
    attrs = f' text="{text}"'
    if node.get("note"):
        note = xml_escape(node["note"], {'"': "&quot;"})
        attrs += f' _note="{note}"'

    children = node.get("children", [])
    if not children:
        return f'{prefix}<outline{attrs} />'
    inner = "\n".join(_to_opml(c, indent + 2) for c in children)
    return f'{prefix}<outline{attrs}>\n{inner}\n{prefix}</outline>'


def _to_freemind(node: dict[str, Any], indent: int = 2) -> str:
    """递归转换为 FreeMind XML（使用 XML 标准转义）。"""
    prefix = " " * indent
    text = xml_escape(node.get("text", ""))
    attrs = f' TEXT="{text}"'
    if node.get("note"):
        note = xml_escape(node["note"])
        attrs += f' NOTE="{note}"'

    children = node.get("children", [])
    if not children:
        return f'{prefix}<node{attrs} />'
    inner = "\n".join(_to_freemind(c, indent + 2) for c in children)
    return f'{prefix}<node{attrs}>\n{inner}\n{prefix}</node>'


def _to_markdown(node: dict[str, Any], level: int = 0) -> str:
    """递归转换为 Markdown 大纲（缩进 + 列表）。"""
    indent = "  " * level
    text = node.get("text", "")
    note = node.get("note", "")
    line = f"{indent}- **{text}**"
    if note:
        line += f" — *{note}*"
    lines = [line]
    for child in node.get("children", []):
        lines.append(_to_markdown(child, level + 1))
    return "\n".join(lines)


@tool
def export_mindmap(
    mindmap_json: str,
    format: str = "opml",
) -> str:
    """
    将思维导图导出为指定格式的文件，返回下载链接。

    Args:
        mindmap_json: 完整的思维导图 JSON 字符串
        format: 导出格式 — opml | mm | markdown | json
    """
    try:
        mindmap: dict[str, Any] = json.loads(mindmap_json)
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"无效的 JSON: {e}"}, ensure_ascii=False)

    root = mindmap.get("root")
    if not root:
        return json.dumps({"success": False, "error": "缺少 root 根节点"}, ensure_ascii=False)

    title = mindmap.get("title", "思维导图")
    safe_title = "".join(c for c in title if c.isalnum() or c in "._- ")[:50].strip() or "mindmap"
    file_id = uuid.uuid4().hex[:8]

    try:
        if format == "opml":
            now_ts = datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
            n_nodes = count_nodes(root)
            body = _to_opml(root)
            opml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<!-- 思维导图: {title} | {n_nodes} 节点 · {max_depth(root)} 层 | 导出: {now_ts} -->\n'
                '<opml version="2.0">\n'
                "  <head>\n"
                f"    <title>{title}</title>\n"
                f"    <dateCreated>{now_ts}</dateCreated>\n"
                "  </head>\n"
                "  <body>\n"
                f"{body}\n"
                "  </body>\n"
                "</opml>\n"
            )
            filename = f"{safe_title}_{file_id}.opml"
            mime = "text/xml"

        elif format == "mm":
            now_ts = datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
            body = _to_freemind(root)
            mm_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<!-- 思维导图: {title} | {count_nodes(root)} 节点 | 导出: {now_ts} -->\n'
                '<map version="1.0.1">\n'
                f"{body}\n"
                "</map>\n"
            )
            filename = f"{safe_title}_{file_id}.mm"
            mime = "text/xml"

        elif format == "markdown":
            n_nodes = count_nodes(root)
            n_depth = max_depth(root)
            now_ts = datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
            content = (
                f"# {title}\n\n"
                f"> 思维导图 · {n_nodes} 个节点 · {n_depth} 层 · 导出于 {now_ts}\n\n"
                f"---\n\n"
                f"{_to_markdown(root)}\n"
            )
            filename = f"{safe_title}_{file_id}.md"
            mime = "text/markdown"
            filepath = _EXPORT_DIR / filename
            filepath.write_text(content, encoding="utf-8")

        elif format == "json":
            n_nodes = count_nodes(root)
            n_depth = max_depth(root)
            export_data = {
                **mindmap,
                "_export": {
                    "version": "1.0",
                    "exported_at": datetime.now(datetime.UTC).isoformat(),
                    "format": "json",
                    "stats": {
                        "node_count": n_nodes,
                        "max_depth": n_depth,
                    },
                },
            }
            content = json.dumps(export_data, ensure_ascii=False, indent=2)
            filename = f"{safe_title}_{file_id}.json"
            mime = "application/json"
            filepath = _EXPORT_DIR / filename
            filepath.write_text(content, encoding="utf-8")

        else:
            return json.dumps({"success": False, "error": f"不支持的格式: {format}"}, ensure_ascii=False)

        # OPML / MM 也写入文件
        if format in ("opml", "mm"):
            filepath = _EXPORT_DIR / filename
            if format == "opml":
                filepath.write_text(opml, encoding="utf-8")
            else:
                filepath.write_text(mm_xml, encoding="utf-8")

        settings = get_settings()
        download_url = f"{settings.file_download_url_prefix}/mindmap_exports/{filename}"
        size_bytes = filepath.stat().st_size

        logger.info(f"思维导图已导出: {filename} ({format}, {size_bytes} bytes)")

        return json.dumps({
            "success": True,
            "filename": filename,
            "download_url": download_url,
            "format": format,
            "mime_type": mime,
            "size_display": f"{size_bytes / 1024:.1f} KB" if size_bytes > 1024 else f"{size_bytes} B",
            "message": f"导图已导出为 {format.upper()} 格式，可通过 download_url 下载",
            "stats": {
                "title": title,
                "node_count": count_nodes(root),
                "max_depth": max_depth(root),
            },
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"export_mindmap 失败: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════
# 工具 4: fetch_url_outline
# ═══════════════════════════════════════════════════════

@tool
def fetch_url_outline(url: str) -> str:
    """
    从网页 URL 抓取标题结构（h1~h6），转换为思维导图框架 JSON。
    适用于用户提供博客/文档链接快速生成导图大纲。

    Args:
        url: 要抓取的网页 URL
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError:
        return json.dumps({
            "success": False,
            "error": "缺少依赖 beautifulsoup4 / httpx，请在 backend 目录执行 uv sync",
        }, ensure_ascii=False)

    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MindMapAgent/1.0)",
        })
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return json.dumps({"success": False, "error": f"请求失败: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": f"网络错误: {e}"}, ensure_ascii=False)

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return json.dumps({"success": False, "error": f"非 HTML 内容: {content_type}"}, ensure_ascii=False)

    try:
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception:
        soup = BeautifulSoup(resp.text, "html.parser")

    # 提取标题
    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else url

    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    if not headings:
        return json.dumps({
            "success": False,
            "error": "页面中未找到标题元素 (h1-h6)，请手动提供大纲",
        }, ensure_ascii=False)

    # 按层级构建树
    root: dict[str, Any] = {
        "id": "n0",
        "text": page_title[:120],
        "note": f"来源: {url}",
        "children": [],
    }
    # 栈：[(节点, 层级)]
    stack: list[tuple[dict[str, Any], int]] = [(root, 0)]

    for h in headings:
        tag_name = h.name  # h1, h2, ...
        level = int(tag_name[1])  # 1, 2, 3...
        text = h.get_text(strip=True)[:200]
        if not text:
            continue

        # 找到合适的父节点（弹出所有层级 >= 当前标题的节点）
        while stack and stack[-1][1] >= level:
            stack.pop()

        parent = stack[-1][0] if stack else root
        parent.setdefault("children", [])

        # 生成正确的 id
        child_idx = len(parent["children"])
        parent_prefix = parent["id"]
        node_id = f"{parent_prefix}-{child_idx}" if parent_prefix != "n0" else f"n{child_idx + 1}"

        new_node: dict[str, Any] = {
            "id": node_id,
            "text": text,
            "children": [],
        }
        parent["children"].append(new_node)
        stack.append((new_node, level))

    now = datetime.now(datetime.UTC).isoformat()
    result = {
        "title": page_title[:120],
        "root": root,
        "meta": {
            "created": now,
            "modified": now,
            "export_formats": ["opml", "mm", "markdown", "json"],
        },
    }

    logger.info(f"URL 大纲提取完成: {url} → {count_nodes(root)} 个节点, 最大深度 {max_depth(root)}")

    return json.dumps({
        "success": True,
        "mindmap_json": result,
        "stats": {
            "title": page_title[:120],
            "node_count": count_nodes(root),
            "max_depth": max_depth(root),
            "source_url": url,
        },
    }, ensure_ascii=False, indent=2)
