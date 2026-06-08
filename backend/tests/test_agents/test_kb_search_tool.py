"""Agent KB 搜索工具并发限流测试。"""

import threading
import time

import pytest

from src.agents.tools.kb_search import _kb_search_semaphore
from src.agents.tools.info import _KB_SEARCH_TOOL_NAME


@pytest.mark.unit
def test_semaphore_exists() -> None:
    """验证全局信号量存在且初始值为 2。"""
    assert _kb_search_semaphore is not None
    assert isinstance(_kb_search_semaphore, threading.BoundedSemaphore)
    # 初始值应为 2（刚创建时 acquire 两次应成功，第三次阻塞）
    assert _kb_search_semaphore.acquire(blocking=False)
    assert _kb_search_semaphore.acquire(blocking=False)
    assert not _kb_search_semaphore.acquire(blocking=False)
    _kb_search_semaphore.release()
    _kb_search_semaphore.release()


@pytest.mark.unit
def test_semaphore_limits_concurrency() -> None:
    """验证信号量正确限制并发数。"""
    active = 0
    max_active = 0
    lock = threading.Lock()

    def _worker() -> None:
        nonlocal active, max_active
        acquired = _kb_search_semaphore.acquire(timeout=1)
        assert acquired
        try:
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
        finally:
            _kb_search_semaphore.release()

    threads = [threading.Thread(target=_worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 同一时刻最多 2 个线程进入
    assert max_active == 2, f"期望 max_active=2, 实际={max_active}"


@pytest.mark.unit
def test_create_kb_search_tool_rejects_empty_ids() -> None:
    """验证空 kb_ids 抛出异常。"""
    from src.agents.tools.info import create_kb_search_tool

    with pytest.raises(ValueError, match="kb_ids"):
        create_kb_search_tool(tenant_id="default", kb_ids=[])


@pytest.mark.unit
def test_create_kb_search_tool_returns_tool() -> None:
    """验证正常创建返回 langchain Tool。"""
    from src.agents.tools.info import create_kb_search_tool

    tool = create_kb_search_tool(
        tenant_id="default",
        kb_ids=["kb-1"],
        kb_names=["测试库"],
    )
    assert tool.name == _KB_SEARCH_TOOL_NAME
    assert "测试库" in tool.description
    # StructuredTool 可通过 .ainvoke() 调用，非直接 callable
    assert callable(getattr(tool, "ainvoke", None)) or callable(getattr(tool, "func", None)) or callable(tool)
