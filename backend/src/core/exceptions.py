"""
自定义异常模块。

定义项目中所有业务异常，统一异常响应格式，
便于前端和客户端统一处理错误。
"""

from typing import Any


class AppException(Exception):
    """应用基础异常，所有业务异常均继承此类。"""

    def __init__(
        self,
        message: str = "服务内部错误",
        code: int = 50000,
        status_code: int = 500,
        detail: Any = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


# ---- 通用异常 ----
class NotFoundError(AppException):
    """资源未找到。"""

    def __init__(self, message: str = "资源未找到", detail: Any = None) -> None:
        super().__init__(message=message, code=40400, status_code=404, detail=detail)


class ValidationError(AppException):
    """参数校验失败。"""

    def __init__(self, message: str = "参数校验失败", detail: Any = None) -> None:
        super().__init__(message=message, code=42200, status_code=422, detail=detail)


class UnauthorizedError(AppException):
    """未认证。"""

    def __init__(self, message: str = "未认证或凭据无效", detail: Any = None) -> None:
        super().__init__(message=message, code=40100, status_code=401, detail=detail)


class ForbiddenError(AppException):
    """无权限。"""

    def __init__(self, message: str = "无访问权限", detail: Any = None) -> None:
        super().__init__(message=message, code=40300, status_code=403, detail=detail)


# ---- 业务异常 ----
class TenantNotFoundError(NotFoundError):
    """租户不存在。"""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            message=f"租户不存在: {tenant_id}",
            detail={"tenant_id": tenant_id},
        )


class ConversationNotFoundError(NotFoundError):
    """会话不存在。"""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(
            message=f"会话不存在: {conversation_id}",
            detail={"conversation_id": conversation_id},
        )


class AgentNotFoundError(NotFoundError):
    """Agent 不存在。"""

    def __init__(self, agent_id: str) -> None:
        super().__init__(
            message=f"Agent 不存在: {agent_id}",
            detail={"agent_id": agent_id},
        )


class LLMError(AppException):
    """LLM 调用异常。"""

    def __init__(self, message: str = "大模型调用失败", detail: Any = None) -> None:
        super().__init__(message=message, code=50001, status_code=500, detail=detail)


class VectorStoreError(AppException):
    """向量数据库异常。"""

    def __init__(self, message: str = "向量数据库操作失败", detail: Any = None) -> None:
        super().__init__(message=message, code=50002, status_code=500, detail=detail)


class DeletionError(AppException):
    """资源删除失败（向量/文件/数据库不一致时抛出）。"""

    def __init__(self, message: str = "删除资源失败", detail: Any = None) -> None:
        super().__init__(message=message, code=50003, status_code=500, detail=detail)


# ---- 认证异常 ----
class UserAlreadyExistsError(AppException):
    """用户已存在。"""

    def __init__(self, field: str, value: str) -> None:
        super().__init__(
            message=f"该{field}已被注册: {value}",
            code=40900,
            status_code=409,
            detail={"field": field, "value": value},
        )


class InvalidVerificationCodeError(AppException):
    """验证码无效或已过期。"""

    def __init__(self) -> None:
        super().__init__(
            message="验证码无效或已过期",
            code=40001,
            status_code=400,
        )


class InvalidCredentialsError(AppException):
    """用户名或密码错误。"""

    def __init__(self) -> None:
        super().__init__(
            message="用户名或密码错误",
            code=40101,
            status_code=401,
        )


class UserNotFoundError(NotFoundError):
    """用户不存在。"""

    def __init__(self, identifier: str) -> None:
        super().__init__(
            message=f"用户不存在: {identifier}",
            detail={"identifier": identifier},
        )
