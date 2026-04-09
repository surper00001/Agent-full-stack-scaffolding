"""
CORS 中间件配置。

根据应用环境自动调整允许的源，
开发环境开放所有源，生产环境仅允许白名单域名。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings


def setup_cors(app: FastAPI) -> None:
    """配置 CORS 中间件。"""
    settings = get_settings()

    if settings.app_env == "production":
        # 生产环境：仅允许白名单（按需配置）
        origins = [
            "https://your-app.com",
            "https://admin.your-app.com",
        ]
    else:
        # 开发环境：开放所有源
        origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
