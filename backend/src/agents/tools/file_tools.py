"""
文件系统工具 — AI 读写代码、搜索文件的基础能力。

工具列表:
- read_file    — 读取文件内容（分页）
- write_file   — 创建/覆盖文件
- edit_file    — 精确字符串替换编辑
- glob_files   — 文件名模式匹配
- grep_files   — 内容正则搜索
- list_dir     — 列出目录内容

安全策略:
- 所有文件操作限制在配置的 workspace 目录内
- check_permissions() 验证路径边界，防止路径穿越攻击
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from loguru import logger
from pydantic import BaseModel, Field

from src.harness.abort_signal import AbortSignal
from src.harness.tool_base import HarnessTool, PermissionResult

# ── 路径安全辅助 ──

def _get_allowed_dirs() -> list[Path]:
    """获取允许文件工具访问的目录列表（带缓存）。"""
    from src.core.config import get_settings
    settings = get_settings()
    workspace = Path(settings.file_tool_workspace_dir).resolve()
    dirs = [workspace]
    for d in settings.file_tool_allowed_dirs:
        resolved = Path(d).resolve()
        if resolved not in dirs:
            dirs.append(resolved)
    # 始终允许沙箱临时目录
    import tempfile
    tmp = Path(tempfile.gettempdir()).resolve()
    if tmp not in dirs:
        dirs.append(tmp)
    return dirs


def _is_path_allowed(target: Path) -> tuple[bool, str]:
    """检查路径是否在允许的目录内。

    Returns:
        (allowed, reason) — allowed=False 时 reason 说明原因。
    """
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError):
        return False, f"无法解析路径: {target}"

    for allowed_dir in _get_allowed_dirs():
        try:
            resolved.relative_to(allowed_dir)
            return True, ""
        except ValueError:
            continue

    return False, (
        f"路径 '{target}' 不在允许的目录内。"
        f"允许的目录: {[str(d) for d in _get_allowed_dirs()]}"
    )


# ── 输入 Schema ──


# ── 输入 Schema ──

class ReadFileInput(BaseModel):
    """读取文件输入。"""
    file_path: str = Field(description="要读取的文件绝对路径")
    offset: int = Field(default=0, ge=0, description="起始行号（从0开始）")
    limit: int = Field(default=200, ge=1, le=2000, description="最多读取行数")


class WriteFileInput(BaseModel):
    """写入文件输入。"""
    file_path: str = Field(description="要写入的文件绝对路径")
    content: str = Field(description="要写入的内容")


class EditFileInput(BaseModel):
    """编辑文件输入 — 精确字符串替换。"""
    file_path: str = Field(description="要编辑的文件绝对路径")
    old_string: str = Field(description="要替换的原始字符串（必须唯一匹配）")
    new_string: str = Field(description="替换后的新字符串")
    replace_all: bool = Field(default=False, description="是否替换所有匹配（默认仅替换第一个）")


class GlobInput(BaseModel):
    """文件名匹配输入。"""
    pattern: str = Field(description="glob 模式，如 '**/*.py' 或 'src/**/*.ts'")
    path: str = Field(default=".", description="搜索起始目录")


class GrepInput(BaseModel):
    """内容搜索输入。"""
    pattern: str = Field(description="正则表达式搜索模式")
    path: str = Field(default=".", description="搜索目录")
    glob: str | None = Field(default=None, description="文件过滤 glob，如 '*.py'")
    output_mode: str = Field(default="content", description="输出模式: content/files_with_matches/count")
    head_limit: int = Field(default=50, description="最多返回条数")
    case_insensitive: bool = Field(default=False, description="是否忽略大小写")


class ListDirInput(BaseModel):
    """列出目录输入。"""
    path: str = Field(default=".", description="目录路径")


# ── 工具实现 ──

class ReadFileTool(HarnessTool[ReadFileInput, str]):
    """读取文件内容。

    支持分页读取（offset + limit），自动处理编码问题。
    """

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "读取文件内容。支持指定起始行和读取行数。"
        "适用场景：查看代码、配置文件、日志等。"
        "注意：文件路径必须是绝对路径。"
    )
    input_schema: ClassVar[type[BaseModel]] = ReadFileInput
    category: ClassVar[str] = "file"
    tags: ClassVar[list[str]] = ["read", "io"]

    def is_read_only(self, input: ReadFileInput) -> bool:
        return True

    def is_concurrency_safe(self, input: ReadFileInput) -> bool:
        # 读不同文件是安全的，但无法在工具层判断 → 保守返回 False
        return False

    def check_permissions(self, input: ReadFileInput) -> PermissionResult:
        """验证文件路径在允许的目录内，防止路径穿越。"""
        allowed, reason = _is_path_allowed(Path(input.file_path))
        if not allowed:
            logger.warning(f"ReadFileTool 权限拒绝: {reason}")
        return PermissionResult(allowed=allowed, reason=reason)

    async def execute(self, input: ReadFileInput, signal: AbortSignal) -> str:
        path = Path(input.file_path).resolve()
        if not path.exists():
            return f"[错误] 文件不存在: {input.file_path}"
        if path.is_dir():
            return f"[错误] 路径是目录而非文件: {input.file_path}"

        try:
            signal.throw_if_aborted()
            content = path.read_text(encoding="utf-8")
            lines = content.split("\n")
            total_lines = len(lines)

            start = min(input.offset, total_lines)
            end = min(start + input.limit, total_lines)
            selected = lines[start:end]

            result = "\n".join(selected)
            header = (
                f"[文件] {input.file_path}\n"
                f"[行 {start+1}-{end} / 共 {total_lines} 行]\n"
            )
            return header + result
        except UnicodeDecodeError:
            return f"[错误] 无法以 UTF-8 编码读取文件（可能是二进制文件）: {input.file_path}"
        except Exception as e:
            return f"[错误] 读取文件失败: {type(e).__name__}: {e}"


class WriteFileTool(HarnessTool[WriteFileInput, str]):
    """创建或覆盖文件。

    会自动创建不存在的父目录。
    """

    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = (
        "创建新文件或覆盖已有文件。会自动创建不存在的父目录。"
        "适用场景：保存生成的代码、配置文件、输出结果等。"
        "⚠️ 此操作会覆盖已有文件，请谨慎使用。"
        "注意：文件路径必须是绝对路径。"
    )
    input_schema: ClassVar[type[BaseModel]] = WriteFileInput
    category: ClassVar[str] = "file"
    tags: ClassVar[list[str]] = ["write", "io"]

    def is_read_only(self, input: WriteFileInput) -> bool:
        return False

    def is_concurrency_safe(self, input: WriteFileInput) -> bool:
        return False  # 写文件不能并发

    def check_permissions(self, input: WriteFileInput) -> PermissionResult:
        """验证文件路径在允许的目录内，防止路径穿越写入系统文件。"""
        allowed, reason = _is_path_allowed(Path(input.file_path))
        if not allowed:
            logger.warning(f"WriteFileTool 权限拒绝: {reason}")
        return PermissionResult(allowed=allowed, reason=reason)

    async def execute(self, input: WriteFileInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        path = Path(input.file_path).resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(input.content, encoding="utf-8")
            size = len(input.content.encode("utf-8"))
            return (
                f"[写入成功] {input.file_path}\n"
                f"大小: {size} bytes, {len(input.content.split(chr(10)))} 行"
            )
        except PermissionError:
            return f"[错误] 没有写入权限: {input.file_path}"
        except Exception as e:
            return f"[错误] 写入文件失败: {type(e).__name__}: {e}"


class EditFileTool(HarnessTool[EditFileInput, str]):
    """精确字符串替换编辑文件。

    使用 old_string → new_string 精确替换，要求 old_string 在文件中唯一。
    这是 AI 编辑文件的首选方式（而非重写整个文件）。
    """

    name: ClassVar[str] = "edit_file"
    description: ClassVar[str] = (
        "精确编辑文件：查找 old_string 并替换为 new_string。"
        "old_string 必须在文件中唯一匹配（除非 replace_all=True）。"
        "适用场景：修改代码片段、更新配置项、修复 bug 等。"
        "⚠️ 如果不确定 old_string 是否唯一，请先用 read_file 确认。"
        "注意：文件路径必须是绝对路径。"
    )
    input_schema: ClassVar[type[BaseModel]] = EditFileInput
    category: ClassVar[str] = "file"
    tags: ClassVar[list[str]] = ["edit", "io"]

    def is_read_only(self, input: EditFileInput) -> bool:
        return False

    def is_concurrency_safe(self, input: EditFileInput) -> bool:
        return False

    def check_permissions(self, input: EditFileInput) -> PermissionResult:
        """验证文件路径在允许的目录内，防止路径穿越编辑系统文件。"""
        allowed, reason = _is_path_allowed(Path(input.file_path))
        if not allowed:
            logger.warning(f"EditFileTool 权限拒绝: {reason}")
        return PermissionResult(allowed=allowed, reason=reason)

    async def execute(self, input: EditFileInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        path = Path(input.file_path).resolve()
        if not path.exists():
            return f"[错误] 文件不存在: {input.file_path}"

        try:
            content = path.read_text(encoding="utf-8")

            if input.old_string not in content:
                return (
                    f"[错误] 未找到要替换的字符串。\n"
                    f"文件: {input.file_path}\n"
                    f"提示：请用 read_file 确认文件内容和 old_string 是否匹配。"
                )

            if input.replace_all:
                count = content.count(input.old_string)
                new_content = content.replace(input.old_string, input.new_string)
            else:
                count = content.count(input.old_string)
                if count > 1:
                    return (
                        f"[错误] old_string 匹配到 {count} 处，必须唯一。\n"
                        f"文件: {input.file_path}\n"
                        f"提示1：请包含更多上下文使匹配唯一。\n"
                        f"提示2：设置 replace_all=true 替换所有匹配。"
                    )
                new_content = content.replace(input.old_string, input.new_string, 1)

            signal.throw_if_aborted()
            path.write_text(new_content, encoding="utf-8")
            return (
                f"[编辑成功] {input.file_path}\n"
                f"替换了 {count} 处匹配"
            )
        except UnicodeDecodeError:
            return f"[错误] 无法以 UTF-8 编码读取文件: {input.file_path}"
        except Exception as e:
            return f"[错误] 编辑文件失败: {type(e).__name__}: {e}"


class GlobTool(HarnessTool[GlobInput, str]):
    """文件名模式匹配搜索。

    支持标准 glob 模式（*、**、?、[abc]），递归搜索。
    """

    name: ClassVar[str] = "glob"
    description: ClassVar[str] = (
        "按文件名模式搜索文件。支持标准 glob 模式。"
        "适用场景：查找特定类型的文件（如 *.py）、定位模块位置等。"
        "示例：pattern='**/*.py' path='src/' → 递归搜索所有 Python 文件。"
    )
    input_schema: ClassVar[type[BaseModel]] = GlobInput
    category: ClassVar[str] = "file"
    tags: ClassVar[list[str]] = ["search", "discovery"]

    def is_read_only(self, input: GlobInput) -> bool:
        return True

    def is_concurrency_safe(self, input: GlobInput) -> bool:
        return True  # 只读查询，完全并发安全

    def check_permissions(self, input: GlobInput) -> PermissionResult:
        """验证搜索路径在允许的目录内。"""
        allowed, reason = _is_path_allowed(Path(input.path))
        if not allowed:
            logger.warning(f"GlobTool 权限拒绝: {reason}")
        return PermissionResult(allowed=allowed, reason=reason)

    async def execute(self, input: GlobInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        base = Path(input.path).resolve()
        if not base.exists():
            return f"[错误] 目录不存在: {input.path}"

        try:
            matches = sorted(base.glob(input.pattern))
            signal.throw_if_aborted()

            # 限制结果数
            max_results = 200
            if len(matches) > max_results:
                truncated = matches[:max_results]
                result = "\n".join(str(m) for m in truncated)
                return (
                    f"[匹配 {len(matches)} 个文件，显示前 {max_results} 个]\n"
                    f"{result}\n"
                    f"... 还有 {len(matches) - max_results} 个文件未显示，请缩小搜索范围。"
                )

            if not matches:
                return f"[无匹配] pattern='{input.pattern}' path='{input.path}'"

            result = "\n".join(str(m) for m in matches)
            return f"[匹配 {len(matches)} 个文件]\n{result}"
        except Exception as e:
            return f"[错误] glob 搜索失败: {type(e).__name__}: {e}"


class GrepTool(HarnessTool[GrepInput, str]):
    """文件内容正则搜索。

    类似 ripgrep，支持正则、文件过滤、大小写不敏感。
    """

    name: ClassVar[str] = "grep"
    description: ClassVar[str] = (
        "在文件内容中搜索正则表达式。类似 grep/rg 命令。"
        "适用场景：搜索函数定义、变量引用、配置项、错误信息等。"
        "支持正则表达式语法，例如 'def\\s+function_name'、'TODO|FIXME'。"
    )
    input_schema: ClassVar[type[BaseModel]] = GrepInput
    category: ClassVar[str] = "file"
    tags: ClassVar[list[str]] = ["search", "discovery"]

    def is_read_only(self, input: GrepInput) -> bool:
        return True

    def is_concurrency_safe(self, input: GrepInput) -> bool:
        return True

    def check_permissions(self, input: GrepInput) -> PermissionResult:
        """验证搜索路径在允许的目录内。"""
        allowed, reason = _is_path_allowed(Path(input.path))
        if not allowed:
            logger.warning(f"GrepTool 权限拒绝: {reason}")
        return PermissionResult(allowed=allowed, reason=reason)

    async def execute(self, input: GrepInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        base = Path(input.path).resolve()
        if not base.exists():
            return f"[错误] 路径不存在: {input.path}"

        try:
            flags = re.IGNORECASE if input.case_insensitive else 0
            regex = re.compile(input.pattern, flags)

            if input.output_mode == "files_with_matches":
                # 只返回文件路径
                matched_files = []
                files = base.rglob(input.glob or "*")
                for f in files:
                    signal.throw_if_aborted()
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(encoding="utf-8")
                        if regex.search(content):
                            matched_files.append(str(f))
                    except (UnicodeDecodeError, PermissionError):
                        continue

                if not matched_files:
                    return "[无匹配文件]"

                result = "\n".join(sorted(matched_files)[:input.head_limit])
                return f"[匹配 {len(matched_files)} 个文件]\n{result}"

            elif input.output_mode == "count":
                count = 0
                files = base.rglob(input.glob or "*")
                for f in files:
                    signal.throw_if_aborted()
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(encoding="utf-8")
                        count += len(regex.findall(content))
                    except (UnicodeDecodeError, PermissionError):
                        continue
                return f"[匹配 {count} 处]"

            else:  # content mode
                results = []
                files = base.rglob(input.glob or "*")
                for f in files:
                    signal.throw_if_aborted()
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(encoding="utf-8")
                        lines = content.split("\n")
                        for i, line in enumerate(lines):
                            if regex.search(line):
                                results.append(f"{f}:{i+1}: {line.strip()[:200]}")
                                if len(results) >= input.head_limit:
                                    break
                    except (UnicodeDecodeError, PermissionError):
                        continue
                    if len(results) >= input.head_limit:
                        break

                if not results:
                    return f"[无匹配] pattern='{input.pattern}'"

                output = "\n".join(results)
                return f"[匹配 {len(results)} 行]\n{output}"

        except re.error as e:
            return f"[错误] 正则表达式无效: {e}"
        except Exception as e:
            return f"[错误] grep 搜索失败: {type(e).__name__}: {e}"


class ListDirTool(HarnessTool[ListDirInput, str]):
    """列出目录内容。"""

    name: ClassVar[str] = "list_dir"
    description: ClassVar[str] = (
        "列出目录中的文件和子目录。"
        "适用场景：了解项目结构、查看目录内容。"
    )
    input_schema: ClassVar[type[BaseModel]] = ListDirInput
    category: ClassVar[str] = "file"
    tags: ClassVar[list[str]] = ["discovery"]

    def is_read_only(self, input: ListDirInput) -> bool:
        return True

    def is_concurrency_safe(self, input: ListDirInput) -> bool:
        return True

    def check_permissions(self, input: ListDirInput) -> PermissionResult:
        """验证目录路径在允许的目录内。"""
        allowed, reason = _is_path_allowed(Path(input.path))
        if not allowed:
            logger.warning(f"ListDirTool 权限拒绝: {reason}")
        return PermissionResult(allowed=allowed, reason=reason)

    async def execute(self, input: ListDirInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        path = Path(input.path).resolve()
        if not path.exists():
            return f"[错误] 目录不存在: {input.path}"
        if not path.is_dir():
            return f"[错误] 不是目录: {input.path}"

        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            lines = []
            for item in items[:100]:
                signal.throw_if_aborted()
                prefix = "📁" if item.is_dir() else "📄"
                size = ""
                if item.is_file():
                    try:
                        s = item.stat().st_size
                        if s < 1024:
                            size = f" ({s}B)"
                        elif s < 1024 * 1024:
                            size = f" ({s/1024:.1f}KB)"
                        else:
                            size = f" ({s/1024/1024:.1f}MB)"
                    except OSError:
                        pass
                lines.append(f"{prefix} {item.name}{size}")

            result = "\n".join(lines)
            return (
                f"[目录] {path} ({len(items)} 项)\n"
                f"{result}"
                + ("\n... 还有更多" if len(items) > 100 else "")
            )
        except PermissionError:
            return f"[错误] 没有读取权限: {input.path}"
        except Exception as e:
            return f"[错误] 列出目录失败: {type(e).__name__}: {e}"
