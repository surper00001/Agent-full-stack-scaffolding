"""
网络工具 — HTTP 请求和数据获取。

工具列表:
- web_fetch  — HTTP GET 请求，获取网页/API 内容
- web_request — 通用 HTTP 请求（GET/POST/PUT/DELETE）
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from src.harness.abort_signal import AbortSignal
from src.harness.tool_base import HarnessTool


class WebFetchInput(BaseModel):
    """HTTP GET 请求输入。"""
    url: str = Field(description="要获取的 URL")
    headers: dict[str, str] | None = Field(default=None, description="自定义请求头")
    max_size_kb: int = Field(default=500, description="最大响应大小（KB）")


class WebRequestInput(BaseModel):
    """通用 HTTP 请求输入。"""
    url: str = Field(description="请求 URL")
    method: str = Field(default="GET", description="HTTP 方法: GET/POST/PUT/DELETE")
    headers: dict[str, str] | None = Field(default=None, description="自定义请求头")
    body: str | None = Field(default=None, description="请求体（JSON 字符串或原始文本）")
    timeout_seconds: int = Field(default=30, description="超时时间")


class WebFetchTool(HarnessTool[WebFetchInput, str]):
    """HTTP GET 请求工具。

    获取网页或 API 内容，自动处理常见编码。
    """

    name: ClassVar[str] = "web_fetch"
    description: ClassVar[str] = (
        "发起 HTTP GET 请求获取网页或 API 内容。"
        "适用场景：调用 REST API、抓取网页内容、获取在线数据等。"
        "注意：响应大小限制 500KB，超时 30 秒。"
    )
    input_schema: ClassVar[type[BaseModel]] = WebFetchInput
    category: ClassVar[str] = "network"
    tags: ClassVar[list[str]] = ["http", "api"]

    def is_read_only(self, input: WebFetchInput) -> bool:
        return True

    def is_concurrency_safe(self, input: WebFetchInput) -> bool:
        return True

    async def execute(self, input: WebFetchInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(
                    input.url,
                    headers=input.headers or {},
                )

                max_bytes = input.max_size_kb * 1024
                content = response.text[:max_bytes]

                truncated = ""
                if len(response.text) > max_bytes:
                    truncated = f"\n[内容已截断，原始大小: {len(response.text)} 字节]"

                return (
                    f"[HTTP {response.status_code}] {input.url}\n"
                    f"Content-Type: {response.headers.get('content-type', 'unknown')}\n"
                    f"大小: {len(content)} 字节{truncated}\n\n"
                    f"{content}"
                )
        except httpx.TimeoutException:
            return f"[超时] 请求 {input.url} 超过 30 秒"
        except httpx.ConnectError:
            return f"[连接失败] 无法连接到 {input.url}"
        except Exception as e:
            return f"[错误] 请求失败: {type(e).__name__}: {e}"


class WebRequestTool(HarnessTool[WebRequestInput, str]):
    """通用 HTTP 请求工具。"""

    name: ClassVar[str] = "web_request"
    description: ClassVar[str] = (
        "发起通用 HTTP 请求（GET/POST/PUT/DELETE）。"
        "适用场景：调用需要特定方法的 API、提交数据等。"
    )
    input_schema: ClassVar[type[BaseModel]] = WebRequestInput
    category: ClassVar[str] = "network"
    tags: ClassVar[list[str]] = ["http", "api"]

    def is_read_only(self, input: WebRequestInput) -> bool:
        return input.method.upper() in ("GET", "HEAD", "OPTIONS")

    def is_concurrency_safe(self, input: WebRequestInput) -> bool:
        return input.method.upper() in ("GET", "HEAD")  # POST 可能有副作用

    async def execute(self, input: WebRequestInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        method = input.method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            return f"[错误] 不支持的 HTTP 方法: {method}"

        try:
            async with httpx.AsyncClient(
                timeout=input.timeout_seconds,
                follow_redirects=True,
            ) as client:
                kwargs: dict[str, Any] = {"headers": input.headers or {}}
                if input.body and method in ("POST", "PUT", "PATCH"):
                    kwargs["content"] = input.body

                response = await client.request(method, input.url, **kwargs)

                content = response.text[:10000]  # 限制输出
                return (
                    f"[HTTP {response.status_code}] {method} {input.url}\n"
                    f"{content}"
                )
        except httpx.TimeoutException:
            return f"[超时] 请求 {input.url} 超过 {input.timeout_seconds} 秒"
        except Exception as e:
            return f"[错误] 请求失败: {type(e).__name__}: {e}"
