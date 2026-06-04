"""
测试系统级工具 — 文件、Shell、网络。
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.harness.abort_signal import AbortSignal
from src.harness.tool_registry import register_tool


# ============================================================
# 文件工具
# ============================================================

class TestReadFileTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.file_tools import ReadFileTool
        register_tool(ReadFileTool())

    @pytest.mark.asyncio
    async def test_read_existing_file(self):
        from src.agents.tools.file_tools import ReadFileInput, ReadFileTool

        tool = ReadFileTool()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")
            tmp = f.name

        try:
            result = await tool.execute(
                ReadFileInput(file_path=tmp, offset=1, limit=2),
                AbortSignal(),
            )
            assert "line2" in result
            assert "line3" in result
            # offset=1, limit=2 → 显示行 2-3 / 共 5 行
            assert "行 2-3" in result or "行 2-3" in result
        finally:
            os.unlink(tmp)

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        from src.agents.tools.file_tools import ReadFileInput, ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(
            ReadFileInput(file_path="/nonexistent/path.txt"),
            AbortSignal(),
        )
        assert "文件不存在" in result

    @pytest.mark.asyncio
    async def test_read_directory_fails(self):
        from src.agents.tools.file_tools import ReadFileInput, ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(
            ReadFileInput(file_path=str(Path(tempfile.gettempdir()))),
            AbortSignal(),
        )
        assert "目录" in result


class TestWriteFileTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.file_tools import WriteFileTool
        register_tool(WriteFileTool())

    @pytest.mark.asyncio
    async def test_write_and_read(self):
        from src.agents.tools.file_tools import ReadFileInput, ReadFileTool, WriteFileInput, WriteFileTool

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test_output.txt"

            # 写入
            w = WriteFileTool()
            result = await w.execute(
                WriteFileInput(file_path=str(filepath), content="hello world\nline2\n"),
                AbortSignal(),
            )
            assert "写入成功" in result
            assert filepath.exists()

            # 读取验证
            r = ReadFileTool()
            result = await r.execute(
                ReadFileInput(file_path=str(filepath)),
                AbortSignal(),
            )
            assert "hello world" in result

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self):
        from src.agents.tools.file_tools import WriteFileInput, WriteFileTool

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b" / "c" / "test.txt"
            w = WriteFileTool()
            result = await w.execute(
                WriteFileInput(file_path=str(nested), content="nested"),
                AbortSignal(),
            )
            assert "写入成功" in result
            assert nested.exists()


class TestEditFileTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.file_tools import EditFileTool
        register_tool(EditFileTool())

    @pytest.mark.asyncio
    async def test_single_replace(self):
        from src.agents.tools.file_tools import EditFileInput, EditFileTool

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "config.py"
            filepath.write_text("DEBUG = True\nHOST = 'localhost'\n")

            tool = EditFileTool()
            result = await tool.execute(
                EditFileInput(
                    file_path=str(filepath),
                    old_string="DEBUG = True",
                    new_string="DEBUG = False",
                ),
                AbortSignal(),
            )
            assert "编辑成功" in result
            assert filepath.read_text() == "DEBUG = False\nHOST = 'localhost'\n"

    @pytest.mark.asyncio
    async def test_duplicate_old_string_rejected(self):
        from src.agents.tools.file_tools import EditFileInput, EditFileTool

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "dupes.txt"
            filepath.write_text("TODO: fix\nTODO: fix\nTODO: fix\n")

            tool = EditFileTool()
            result = await tool.execute(
                EditFileInput(
                    file_path=str(filepath),
                    old_string="TODO: fix",
                    new_string="DONE",
                ),
                AbortSignal(),
            )
            assert "匹配到 3 处" in result
            assert "必须唯一" in result
            # 文件未被修改
            assert filepath.read_text().count("TODO") == 3

    @pytest.mark.asyncio
    async def test_replace_all(self):
        from src.agents.tools.file_tools import EditFileInput, EditFileTool

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "dupes.txt"
            filepath.write_text("TODO\nTODO\nTODO\n")

            tool = EditFileTool()
            result = await tool.execute(
                EditFileInput(
                    file_path=str(filepath),
                    old_string="TODO",
                    new_string="DONE",
                    replace_all=True,
                ),
                AbortSignal(),
            )
            assert "编辑成功" in result
            assert filepath.read_text() == "DONE\nDONE\nDONE\n"

    @pytest.mark.asyncio
    async def test_not_found(self):
        from src.agents.tools.file_tools import EditFileInput, EditFileTool

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "data.txt"
            filepath.write_text("hello")

            tool = EditFileTool()
            result = await tool.execute(
                EditFileInput(
                    file_path=str(filepath),
                    old_string="nonexistent",
                    new_string="replacement",
                ),
                AbortSignal(),
            )
            assert "未找到" in result


class TestGlobTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.file_tools import GlobTool
        register_tool(GlobTool())

    @pytest.mark.asyncio
    async def test_find_python_files(self):
        from src.agents.tools.file_tools import GlobInput, GlobTool

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").touch()
            (Path(tmpdir) / "b.py").touch()
            (Path(tmpdir) / "c.txt").touch()

            tool = GlobTool()
            result = await tool.execute(
                GlobInput(pattern="*.py", path=tmpdir),
                AbortSignal(),
            )
            assert "匹配 2" in result
            assert "a.py" in result
            assert "b.py" in result
            assert "c.txt" not in result

    @pytest.mark.asyncio
    async def test_recursive_search(self):
        from src.agents.tools.file_tools import GlobInput, GlobTool

        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "sub"
            sub.mkdir()
            (Path(tmpdir) / "root.py").touch()
            (sub / "sub.py").touch()

            tool = GlobTool()
            result = await tool.execute(
                GlobInput(pattern="**/*.py", path=tmpdir),
                AbortSignal(),
            )
            assert "匹配 2" in result


class TestGrepTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.file_tools import GrepTool
        register_tool(GrepTool())

    @pytest.mark.asyncio
    async def test_search_content(self):
        from src.agents.tools.file_tools import GrepInput, GrepTool

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("def hello():\n    return 'world'\n")
            (Path(tmpdir) / "b.py").write_text("print('no match')\n")

            tool = GrepTool()
            result = await tool.execute(
                GrepInput(pattern="def hello", path=tmpdir),
                AbortSignal(),
            )
            assert "def hello" in result
            assert "a.py" in result

    @pytest.mark.asyncio
    async def test_files_with_matches_mode(self):
        from src.agents.tools.file_tools import GrepInput, GrepTool

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("TODO: fix this\n")
            (Path(tmpdir) / "b.py").write_text("TODO: fix that\n")
            (Path(tmpdir) / "c.py").write_text("all done\n")

            tool = GrepTool()
            result = await tool.execute(
                GrepInput(pattern="TODO", path=tmpdir, output_mode="files_with_matches"),
                AbortSignal(),
            )
            assert "匹配 2" in result
            assert "c.py" not in result

    @pytest.mark.asyncio
    async def test_count_mode(self):
        from src.agents.tools.file_tools import GrepInput, GrepTool

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("TODO: a\nTODO: b\nDONE\n")

            tool = GrepTool()
            result = await tool.execute(
                GrepInput(pattern="TODO", path=tmpdir, output_mode="count"),
                AbortSignal(),
            )
            assert "匹配 2" in result


# ============================================================
# Shell 工具
# ============================================================

class TestShellTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.shell_tool import RunShellTool
        register_tool(RunShellTool())

    @pytest.mark.asyncio
    async def test_simple_command(self):
        from src.agents.tools.shell_tool import RunShellInput, RunShellTool

        tool = RunShellTool()
        result = await tool.execute(
            RunShellInput(command="echo hello world"),
            AbortSignal(),
        )
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_command_in_working_dir(self):
        from src.agents.tools.shell_tool import RunShellInput, RunShellTool

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = RunShellTool()
            result = await tool.execute(
                RunShellInput(command="pwd" if os.name != "nt" else "cd", working_dir=tmpdir),
                AbortSignal(),
            )
            assert tmpdir in result or "退出码" in result

    @pytest.mark.asyncio
    async def test_forbidden_command(self):
        from src.agents.tools.shell_tool import RunShellInput, RunShellTool

        tool = RunShellTool()
        perm = tool.check_permissions(
            RunShellInput(command="rm -rf /")
        )
        assert not perm.allowed
        assert "危险" in perm.reason

    @pytest.mark.asyncio
    async def test_failed_command(self):
        from src.agents.tools.shell_tool import RunShellInput, RunShellTool

        tool = RunShellTool()
        result = await tool.execute(
            RunShellInput(command="nonexistent_command_xyz 2>&1 || true"),
            AbortSignal(),
        )
        assert "错误" in result or "退出码" in result


# ============================================================
# 网络工具
# ============================================================

class TestWebFetchTool:
    @pytest.fixture(autouse=True)
    def setup(self):
        from src.agents.tools.network_tools import WebFetchTool
        register_tool(WebFetchTool())

    @pytest.mark.asyncio
    async def test_is_read_only(self):
        from src.agents.tools.network_tools import WebFetchInput, WebFetchTool

        tool = WebFetchTool()
        assert tool.is_read_only(WebFetchInput(url="https://example.com"))
        assert tool.is_concurrency_safe(WebFetchInput(url="https://example.com"))

    @pytest.mark.asyncio
    async def test_fetch_invalid_url(self):
        from src.agents.tools.network_tools import WebFetchInput, WebFetchTool

        tool = WebFetchTool()
        result = await tool.execute(
            WebFetchInput(url="http://invalid.does.not.exist.example"),
            AbortSignal(),
        )
        assert "连接失败" in result or "错误" in result


# ============================================================
# HarnessTool 接口验证
# ============================================================

class TestToolInterfaces:
    """验证所有新工具都正确实现了 HarnessTool 接口。"""

    def test_all_tools_have_required_attributes(self):
        """每个工具必须定义 name, description, input_schema, category。"""
        from src.agents.tools.file_tools import (
            EditFileTool,
            GlobTool,
            GrepTool,
            ListDirTool,
            ReadFileTool,
            WriteFileTool,
        )
        from src.agents.tools.network_tools import WebFetchTool, WebRequestTool
        from src.agents.tools.shell_tool import RunShellTool

        all_tools = [
            ReadFileTool, WriteFileTool, EditFileTool,
            GlobTool, GrepTool, ListDirTool,
            RunShellTool,
            WebFetchTool, WebRequestTool,
        ]

        for tool_cls in all_tools:
            tool = tool_cls()
            assert tool.name, f"{tool_cls.__name__} 缺少 name"
            assert tool.description, f"{tool_cls.__name__} 缺少 description"
            assert tool.input_schema, f"{tool_cls.__name__} 缺少 input_schema"
            assert tool.category, f"{tool_cls.__name__} 缺少 category"
            print(f"  ✓ {tool.name} ({tool.category})")

    @pytest.mark.asyncio
    async def test_readonly_vs_concurrency_distinction(self):
        """验证关键工具的 is_read_only / is_concurrency_safe 区分正确。"""
        from src.agents.tools.file_tools import (
            EditFileInput,
            EditFileTool,
            GrepInput,
            GrepTool,
            ReadFileInput,
            ReadFileTool,
            WriteFileInput,
            WriteFileTool,
        )
        from src.agents.tools.network_tools import WebFetchInput, WebFetchTool, WebRequestInput, WebRequestTool
        from src.agents.tools.shell_tool import RunShellInput, RunShellTool

        # grep: 只读 ✓, 并发安全 ✓
        grep = GrepTool()
        assert grep.is_read_only(GrepInput(pattern="test"))
        assert grep.is_concurrency_safe(GrepInput(pattern="test"))

        # read_file: 只读 ✓, 并发安全 ✗ (同文件指针)
        rf = ReadFileTool()
        assert rf.is_read_only(ReadFileInput(file_path="/test"))
        assert not rf.is_concurrency_safe(ReadFileInput(file_path="/test"))

        # write_file: 只读 ✗, 并发安全 ✗
        wf = WriteFileTool()
        assert not wf.is_read_only(WriteFileInput(file_path="/t.txt", content="x"))
        assert not wf.is_concurrency_safe(WriteFileInput(file_path="/t.txt", content="x"))

        # edit_file: 只读 ✗, 并发安全 ✗
        ef = EditFileTool()
        assert not ef.is_read_only(EditFileInput(file_path="/t.txt", old_string="a", new_string="b"))
        assert not ef.is_concurrency_safe(EditFileInput(file_path="/t.txt", old_string="a", new_string="b"))

        # web_fetch: 只读 ✓, 并发安全 ✓
        wf2 = WebFetchTool()
        assert wf2.is_read_only(WebFetchInput(url="http://test"))
        assert wf2.is_concurrency_safe(WebFetchInput(url="http://test"))

        # web_request POST: 只读 ✗, 并发安全 ✗
        wr = WebRequestTool()
        assert not wr.is_read_only(WebRequestInput(url="http://test", method="POST"))
        assert not wr.is_concurrency_safe(WebRequestInput(url="http://test", method="POST"))

        # run_shell: 只读 ✗, 并发安全 ✗
        rs = RunShellTool()
        assert not rs.is_read_only(RunShellInput(command="echo test"))
        assert not rs.is_concurrency_safe(RunShellInput(command="echo test"))

        print("  ✓ 所有工具的 is_read_only/is_concurrency_safe 语义正确")
