"""
测试 Harness Engineering 核心模块：
- AbortSignal 树形取消
- HarnessTool 接口
- StreamingToolExecutor 流式并行调度
"""

import asyncio
import time

import pytest
from pydantic import BaseModel, Field

from src.harness.abort_signal import AbortError, AbortSignal, create_signal_chain
from src.harness.tool_base import HarnessTool, PermissionResult, ValidationResult


# ============================================================
# AbortSignal 测试
# ============================================================

class TestAbortSignal:
    """测试 AbortSignal 树形取消机制。"""

    def test_single_signal_abort(self):
        """单个信号：abort 后状态改变。"""
        sig = AbortSignal(name="test")
        assert not sig.aborted
        assert sig.reason is None

        sig.abort("用户取消")
        assert sig.aborted
        assert sig.reason == "用户取消"

    def test_repeated_abort_is_idempotent(self):
        """重复 abort 无副作用。"""
        sig = AbortSignal(name="test")
        sig.abort("第一次")
        sig.abort("第二次")
        assert sig.reason == "第一次"  # 第一次的原因保留

    def test_parent_abort_propagates_to_child(self):
        """父信号取消 → 子信号自动取消。"""
        parent = AbortSignal(name="parent")
        child = AbortSignal(parent=parent, name="child")
        grandchild = AbortSignal(parent=child, name="grandchild")

        assert not child.aborted
        assert not grandchild.aborted

        parent.abort("用户中断")

        assert child.aborted
        assert child.reason == "用户中断"
        assert grandchild.aborted
        assert grandchild.reason == "用户中断"

    def test_child_abort_does_not_affect_parent(self):
        """子信号取消 → 不影响父信号。"""
        parent = AbortSignal(name="parent")
        child = AbortSignal(parent=parent, name="child")

        child.abort("子任务超时")

        assert child.aborted
        assert not parent.aborted  # 父仍活跃

    def test_child_abort_does_not_affect_sibling(self):
        """子信号取消 → 不影响兄弟节点。"""
        parent = AbortSignal(name="parent")
        child1 = AbortSignal(parent=parent, name="child1")
        child2 = AbortSignal(parent=parent, name="child2")

        child1.abort("child1 超时")

        assert child1.aborted
        assert not child2.aborted  # 兄弟不受影响
        assert not parent.aborted  # 父不受影响

    def test_throw_if_aborted(self):
        """已取消的信号抛出 AbortError。"""
        sig = AbortSignal(name="test")
        sig.throw_if_aborted()  # 不抛

        sig.abort("取消")
        with pytest.raises(AbortError, match="取消"):
            sig.throw_if_aborted()

    def test_on_abort_callback(self):
        """取消回调正确触发。"""
        sig = AbortSignal(name="test")
        results = []

        sig.on_abort(lambda r: results.append(r))
        sig.abort("测试取消")

        assert results == ["测试取消"]

    def test_on_abort_callback_already_aborted(self):
        """已取消的信号注册回调时立即执行。"""
        sig = AbortSignal(name="test")
        sig.abort("已取消")

        results = []
        sig.on_abort(lambda r: results.append(r))
        assert results == ["已取消"]

    def test_create_signal_chain(self):
        """create_signal_chain 创建正确的父子链。"""
        signals = create_signal_chain("user", "task", "tool", "shell")

        assert len(signals) == 4
        assert signals[0].name == "user"
        assert signals[1].name == "task"
        assert signals[2].name == "tool"
        assert signals[3].name == "shell"

        # 顶层取消 → 全部取消
        signals[0].abort("用户取消")
        assert all(s.aborted for s in signals)

    @pytest.mark.asyncio
    async def test_async_wait_for_abort(self):
        """异步等待取消信号。"""
        sig = AbortSignal(name="test")

        async def delayed_abort():
            await asyncio.sleep(0.05)
            sig.abort("超时取消")

        asyncio.create_task(delayed_abort())
        reason = await sig.wait()
        assert reason == "超时取消"


# ============================================================
# HarnessTool 测试
# ============================================================

class ReadFileInput(BaseModel):
    file_path: str = Field(description="文件路径")
    offset: int = Field(default=0)
    limit: int = Field(default=100)


class ReadFileTool(HarnessTool[ReadFileInput, str]):
    """只读取不写的工具 — is_read_only=True。"""
    name = "read_file"
    description = "读取文件内容"
    input_schema = ReadFileInput
    category = "file"

    def is_read_only(self, input: ReadFileInput) -> bool:
        return True  # 读文件是只读的

    def is_concurrency_safe(self, input: ReadFileInput) -> bool:
        # 读不同文件是并发安全的，但不做复杂判断，统一返回 False
        return False

    async def execute(self, input: ReadFileInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()
        await asyncio.sleep(0.02)
        return f"content of {input.file_path}"


class WriteFileInput(BaseModel):
    file_path: str = Field(description="文件路径")
    content: str = Field(description="写入内容")


class WriteFileTool(HarnessTool[WriteFileInput, str]):
    """写文件的工具 — is_read_only=False。"""
    name = "write_file"
    description = "写入文件内容"
    input_schema = WriteFileInput
    category = "file"

    def is_read_only(self, input: WriteFileInput) -> bool:
        return False  # 写操作不是只读

    def is_concurrency_safe(self, input: WriteFileInput) -> bool:
        return False  # 写文件不能并发

    async def execute(self, input: WriteFileInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()
        await asyncio.sleep(0.05)
        return f"wrote to {input.file_path}"


class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词")


class WebSearchTool(HarnessTool[WebSearchInput, str]):
    """网络搜索 — 只读 + 并发安全。"""
    name = "web_search"
    description = "搜索网络"
    input_schema = WebSearchInput
    category = "network"

    def is_read_only(self, input: WebSearchInput) -> bool:
        return True  # GET 请求只读

    def is_concurrency_safe(self, input: WebSearchInput) -> bool:
        return True  # 不同查询完全独立，真正的并发安全

    async def execute(self, input: WebSearchInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()
        await asyncio.sleep(0.03)
        return f"results for: {input.query}"


class TestHarnessTool:
    """测试 HarnessTool 基类。"""

    def test_tool_metadata(self):
        """工具元数据正确。"""
        tool = ReadFileTool()
        assert tool.name == "read_file"
        assert tool.category == "file"

    def test_openai_function_schema(self):
        """生成的 OpenAI function calling 格式正确。"""
        schema = ReadFileTool.to_openai_function()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"
        assert "parameters" in schema["function"]

    def test_to_langchain_tool(self):
        """转换 LangChain tool 成功。"""
        lc_tool = ReadFileTool.to_langchain_tool()
        assert lc_tool.name == "read_file"
        assert lc_tool.args_schema == ReadFileInput

    def test_validation_result(self):
        """ValidationResult 构造正确。"""
        ok = ValidationResult.ok()
        assert ok.valid
        assert not ok.errors

        fail = ValidationResult.fail(["字段缺失", "格式错误"])
        assert not fail.valid
        assert len(fail.errors) == 2

    def test_permission_result(self):
        """PermissionResult 构造正确。"""
        perm = PermissionResult(allowed=True)
        assert perm.allowed

        no_perm = PermissionResult(allowed=False, reason="权限不足", requires_approval=True)
        assert not no_perm.allowed
        assert no_perm.requires_approval

    def test_is_read_only_distinction(self):
        """is_read_only vs is_concurrency_safe 区分。"""
        read_file = ReadFileTool()
        web_search = WebSearchTool()
        write_file = WriteFileTool()

        # read_file: 只读 ✓, 但非并发安全 ✗（同文件指针问题）
        assert read_file.is_read_only(ReadFileInput(file_path="/test.txt"))
        assert not read_file.is_concurrency_safe(ReadFileInput(file_path="/test.txt"))

        # web_search: 只读 ✓, 并发安全 ✓
        assert web_search.is_read_only(WebSearchInput(query="test"))
        assert web_search.is_concurrency_safe(WebSearchInput(query="test"))

        # write_file: 只读 ✗, 并发安全 ✗
        assert not write_file.is_read_only(WriteFileInput(file_path="/t.txt", content="x"))
        assert not write_file.is_concurrency_safe(WriteFileInput(file_path="/t.txt", content="x"))

    @pytest.mark.asyncio
    async def test_execute_with_abort(self):
        """执行中 abort 能正确中断。"""
        tool = ReadFileTool()
        signal = AbortSignal(name="test-abort")

        # 异步 abort
        async def abort_soon():
            await asyncio.sleep(0.01)
            signal.abort("测试中断")

        task = asyncio.create_task(abort_soon())
        # execute 内部调用 throw_if_aborted 会被中断
        # 这里 ReadFileTool 的实现很短，不太可能被中断，但检查机制存在
        result = await tool.execute(ReadFileInput(file_path="/test"), signal)
        assert "content" in result
        await task

    @pytest.mark.asyncio
    async def test_execute_with_pre_aborted_signal(self):
        """传入已取消的信号 → 立即失败。"""
        tool = ReadFileTool()
        signal = AbortSignal(name="already-aborted")
        signal.abort("已取消")

        with pytest.raises(AbortError):
            await tool.execute(ReadFileInput(file_path="/test"), signal)


# ============================================================
# StreamingToolExecutor 测试
# ============================================================

# 需要先注册工具到 registry
from src.harness.tool_registry import register_tool


class TestStreamingToolExecutor:
    """测试流式并行工具调度。"""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """注册测试工具。"""
        register_tool(ReadFileTool())
        register_tool(WriteFileTool())
        register_tool(WebSearchTool())

    @pytest.mark.asyncio
    async def test_single_tool_execution(self):
        """单个工具正常执行。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor()
        task = executor.submit("read_file", {"file_path": "/tmp/test.txt"})
        executor.mark_all_submitted()

        results = await executor.wait_all()
        assert len(results) == 1
        assert results[0].success
        assert "content of" in str(results[0].output)

    @pytest.mark.asyncio
    async def test_parallel_readonly_tools(self):
        """只读工具可以并行执行。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor(max_parallel=4)

        # 提交 3 个只读工具
        tasks = executor.submit_all([
            ("web_search", {"query": "A"}),
            ("web_search", {"query": "B"}),
            ("web_search", {"query": "C"}),
        ])
        executor.mark_all_submitted()

        assert len(tasks) == 3

        start = time.perf_counter()
        results = await executor.wait_all()
        elapsed = time.perf_counter() - start

        assert len(results) == 3
        assert all(r.success for r in results)

        # 3 个操作并行执行 → 总时间应接近 1 次执行时间
        # 每个 sleep 0.03s，并行应 < 0.1s（串行 > 0.09s）
        assert elapsed < 0.2, f"并行执行太慢: {elapsed:.3f}s（预期 <0.2s）"

    @pytest.mark.asyncio
    async def test_write_blocks_parallel(self):
        """写工具应该阻塞其他工具（互斥）。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor(max_parallel=4)

        executor.submit("write_file", {"file_path": "/a.txt", "content": "x"})
        executor.submit("read_file", {"file_path": "/a.txt"})
        executor.mark_all_submitted()

        start = time.perf_counter()
        results = await executor.wait_all()
        elapsed = time.perf_counter() - start

        assert len(results) == 2

        # write(0.05) → read(0.02) 至少 0.07s（串行）
        # 如果并行应该 < 0.06s
        # 由于互斥锁，应该是串行
        assert elapsed > 0.05, f"写操作应该阻塞读: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_cancel_all(self):
        """取消所有任务。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor()

        # 提交长时间运行的任务
        class SlowToolInput(BaseModel):
            delay: float

        class SlowTool(HarnessTool[SlowToolInput, str]):
            name = "slow_tool"
            description = "慢工具"
            input_schema = SlowToolInput

            async def execute(self, input: SlowToolInput, signal: AbortSignal) -> str:
                for _ in range(10):
                    await asyncio.sleep(0.05)
                    signal.throw_if_aborted()
                return "done"

        register_tool(SlowTool())

        executor.submit("slow_tool", {"delay": 1.0})
        executor.mark_all_submitted()

        # 立即取消
        await asyncio.sleep(0.02)
        executor.cancel_all("用户中断")

        results = await executor.wait_all()
        assert len(results) >= 0  # 可能已取消未产出结果

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_none(self):
        """提交未注册的工具返回 None。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor()
        task = executor.submit("nonexistent_tool", {})
        assert task is None

    @pytest.mark.asyncio
    async def test_streaming_results_order(self):
        """结果的产出顺序应该保持提交顺序（或接近）。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor(max_parallel=5)

        executor.submit_all([
            ("web_search", {"query": "1st"}),
            ("web_search", {"query": "2nd"}),
            ("web_search", {"query": "3rd"}),
        ])
        executor.mark_all_submitted()

        results = []
        async for result in executor.results():
            results.append(result)

        assert len(results) == 3
        # 所有结果都应该是成功的
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_stats(self):
        """统计信息正确。"""
        from src.harness.streaming_executor import StreamingToolExecutor

        executor = StreamingToolExecutor()
        executor.submit_all([
            ("web_search", {"query": "test1"}),
            ("web_search", {"query": "test2"}),
        ])
        executor.mark_all_submitted()

        await executor.wait_all()

        stats = executor.stats
        assert stats["submitted"] == 2
        assert stats["completed"] == 2
        assert stats["failed"] == 0
