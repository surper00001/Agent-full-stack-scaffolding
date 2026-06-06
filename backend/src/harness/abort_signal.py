"""
AbortSignal — 可组合的树形取消信号。

核心特性：
- 父取消 → 子全部自动取消（单向继承）
- 支持多级树：user_abort → task_abort → tool_abort → shell_abort
- 工具内定期调用 throw_if_aborted() 检查取消状态

使用示例：
    main_signal = AbortSignal()                  # 用户中断入口
    task_signal = AbortSignal(parent=main_signal) # 任务级别
    shell_signal = AbortSignal(parent=task_signal) # Shell 超时

    main_signal.abort("用户取消")  → 所有子信号自动取消
    task_signal.abort("任务超时")  → 只影响 task 及以下
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable


class AbortError(Exception):
    """工具执行被取消时抛出。"""

    def __init__(self, reason: str = "操作已取消") -> None:
        self.reason = reason
        super().__init__(reason)


class AbortSignal:
    """
    可组合的取消信号。

    父信号 abort 时，所有子信号自动 abort。
    每个信号独立可 abort，只影响自身及子树。
    """

    def __init__(self, parent: AbortSignal | None = None, name: str = "") -> None:
        self._name = name or f"signal-{id(self):x}"
        self._aborted = asyncio.Event()
        self._reason: str | None = None
        self._callbacks: list[Callable[[str], None]] = []
        self._parent: AbortSignal | None = None
        self._children: list[AbortSignal] = []

        # 绑定父信号：父取消 → 子自动取消
        if parent is not None:
            self._parent = parent
            parent._children.append(self)
            parent.on_abort(lambda reason: self.abort(reason))

    @property
    def aborted(self) -> bool:
        """是否已取消。"""
        return self._aborted.is_set()

    @property
    def reason(self) -> str | None:
        """取消原因。"""
        return self._reason

    @property
    def name(self) -> str:
        return self._name

    def abort(self, reason: str = "cancelled") -> None:
        """触发取消。已取消的信号重复调用无副作用。"""
        if self._aborted.is_set():
            return
        self._reason = reason
        self._aborted.set()
        for cb in self._callbacks:
            try:
                cb(reason)
            except Exception:
                pass  # 回调异常不影响取消传播

    def on_abort(self, callback: Callable[[str], None]) -> None:
        """注册取消回调。如果已取消则立即执行。"""
        if self._aborted.is_set() and self._reason:
            callback(self._reason)
            return
        self._callbacks.append(callback)

    def throw_if_aborted(self) -> None:
        """检查是否已取消，已取消则抛出 AbortError。

        工具实现中应定期调用此方法，支持在执行中途响应取消。
        """
        if self._aborted.is_set():
            raise AbortError(self._reason or "操作已取消")

    async def wait(self) -> str:
        """等待取消信号，返回取消原因。"""
        await self._aborted.wait()
        return self._reason or "cancelled"

    def create_child(self, name: str = "") -> AbortSignal:
        """创建子信号，自动继承本信号的取消。"""
        return AbortSignal(parent=self, name=name)

    def __repr__(self) -> str:
        status = "ABORTED" if self.aborted else "active"
        return f"<AbortSignal({self._name!r}) {status}>"


def create_signal_chain(*names: str) -> list[AbortSignal]:
    """
    快速创建取消信号链。

    create_signal_chain("user", "task", "tool", "shell")
    返回 [user_signal, task_signal, tool_signal, shell_signal]
    每级都是上一级的子信号。
    """
    signals: list[AbortSignal] = []
    parent: AbortSignal | None = None
    for name in names:
        sig = AbortSignal(parent=parent, name=name)
        signals.append(sig)
        parent = sig
    return signals
