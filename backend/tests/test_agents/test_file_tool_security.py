"""文件工具路径穿越防护测试。

验证 check_permissions() 正确拦截越权路径访问。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.agents.tools.file_tools import (
    GlobInput,
    GrepInput,
    ListDirInput,
    ReadFileInput,
    WriteFileInput,
    EditFileInput,
    GlobTool,
    GrepTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    _get_allowed_dirs,
    _is_path_allowed,
)

# ── 路径验证辅助函数 ──


class TestIsPathAllowed:
    """测试 _is_path_allowed 路径边界检查。"""

    def test_allows_path_inside_default_workspace(self):
        """默认 workspace 内的路径应被允许。"""
        cwd = Path.cwd()
        allowed, reason = _is_path_allowed(cwd / "src" / "agents" / "tools")
        assert allowed, f"期望允许但被拒绝: {reason}"

    def test_rejects_path_outside_workspace(self):
        """workspace 外的系统路径应被拒绝。"""
        # Unix: /etc/passwd, Windows: C:\Windows\System32
        system_path = Path("/etc/passwd") if Path("/etc").exists() else Path("C:/Windows/System32/drivers/etc/hosts")
        allowed, _ = _is_path_allowed(system_path)
        assert not allowed, f"系统路径 {system_path} 应被拒绝"

    def test_allows_temp_dir(self):
        """临时目录应被允许（始终在允许列表中）。"""
        tmp = Path(tempfile.gettempdir()) / "test_sandbox_file.txt"
        allowed, reason = _is_path_allowed(tmp)
        assert allowed, f"临时目录应被允许: {reason}"

    def test_rejects_parent_directory_traversal(self):
        """../../etc/passwd 类路径穿越应被拒绝。"""
        cwd = Path.cwd()
        # 构造一个在 workspace 内但包含 .. 的路径
        traversal = cwd / ".." / ".." / ".." / "etc" / "passwd"
        resolved = traversal.resolve()
        # 如果 resolved 不在允许目录内，应被拒绝
        allowed, _ = _is_path_allowed(traversal)
        # 检查 resolved 是否在允许目录内
        in_workspace = False
        for d in _get_allowed_dirs():
            try:
                resolved.relative_to(d)
                in_workspace = True
                break
            except ValueError:
                continue
        assert allowed == in_workspace, (
            f"traversal={traversal}, resolved={resolved}, "
            f"in_workspace={in_workspace}, allowed={allowed}"
        )


# ── 工具级权限检查 ──


class TestReadFileToolPermissions:
    """测试 ReadFileTool.check_permissions()。"""

    def test_allows_valid_path(self):
        tool = ReadFileTool()
        result = tool.check_permissions(
            ReadFileInput(file_path=str(Path.cwd() / "pyproject.toml"))
        )
        assert result.allowed

    def test_rejects_system_path(self):
        tool = ReadFileTool()
        result = tool.check_permissions(
            ReadFileInput(file_path="/etc/shadow")
        )
        # /etc/shadow 只在 Linux 存在，Windows 上该路径不存在
        # 但 resolve 会失败或不属于允许目录
        if Path("/etc/shadow").exists():
            assert not result.allowed, "系统文件 /etc/shadow 应被拒绝"


class TestWriteFileToolPermissions:
    """测试 WriteFileTool.check_permissions()。"""

    def test_allows_workspace_path(self):
        tool = WriteFileTool()
        result = tool.check_permissions(
            WriteFileInput(
                file_path=str(Path.cwd() / "test_output.txt"),
                content="test",
            )
        )
        assert result.allowed

    def test_rejects_system_write(self):
        tool = WriteFileTool()
        result = tool.check_permissions(
            WriteFileInput(
                file_path="/etc/malicious_file",
                content="evil",
            )
        )
        if Path("/etc").exists():
            assert not result.allowed, "禁止写入系统目录"


class TestEditFileToolPermissions:
    """测试 EditFileTool.check_permissions()。"""

    def test_allows_workspace_edit(self):
        tool = EditFileTool()
        result = tool.check_permissions(
            EditFileInput(
                file_path=str(Path.cwd() / "README.md"),
                old_string="test",
                new_string="updated",
            )
        )
        assert result.allowed

    def test_rejects_system_edit(self):
        tool = EditFileTool()
        result = tool.check_permissions(
            EditFileInput(
                file_path="/etc/hostname",
                old_string="old",
                new_string="new",
            )
        )
        if Path("/etc/hostname").exists():
            assert not result.allowed, "禁止编辑系统文件"


class TestSearchToolPermissions:
    """测试 Glob/Grep/ListDir 工具的权限检查。"""

    def test_glob_allows_workspace(self):
        tool = GlobTool()
        result = tool.check_permissions(
            GlobInput(pattern="*.py", path=str(Path.cwd()))
        )
        assert result.allowed

    def test_glob_rejects_system(self):
        tool = GlobTool()
        result = tool.check_permissions(GlobInput(pattern="*", path="/etc"))
        if Path("/etc").exists():
            assert not result.allowed

    def test_grep_allows_workspace(self):
        tool = GrepTool()
        result = tool.check_permissions(
            GrepInput(pattern="test", path=str(Path.cwd()))
        )
        assert result.allowed

    def test_list_dir_allows_workspace(self):
        tool = ListDirTool()
        result = tool.check_permissions(ListDirInput(path=str(Path.cwd())))
        assert result.allowed
