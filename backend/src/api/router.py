"""
API 路由聚合模块。

将所有子路由注册到主路由上，统一管理版本化 API。
"""

from fastapi import APIRouter

from src.api.v1 import agents, auth, conversations, health

# 创建 v1 版本路由
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(agents.router)
api_v1_router.include_router(conversations.router)

# 根路由
root_router = APIRouter()
root_router.include_router(api_v1_router)
