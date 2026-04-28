// 应用级常量配置

/** API 基础路径 — 由环境变量 VITE_API_BASE_URL 配置，未设置时回退为同源 /api/v1 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

/** 认证Token存储键名 */
export const AUTH_TOKEN_KEY = "agent_platform_token";

/** 刷新Token存储键名 */
export const REFRESH_TOKEN_KEY = "agent_platform_refresh";

/** 分页默认大小 */
export const DEFAULT_PAGE_SIZE = 20;

/** 请求超时时间（毫秒） */
export const REQUEST_TIMEOUT = 30000;

/** 知识库检索 / 重建索引（含首次加载 Reranker）超时 */
export const KB_SEARCH_TIMEOUT = 120000;

/** 知识库文档上传超时（大 PDF / 慢网络，与 KB_MAX_FILE_SIZE_MB=50 匹配） */
export const KB_UPLOAD_TIMEOUT = 300000;

/** 对话上下文窗口上限（与后端 CONTEXT_MAX_TOKENS 保持一致） */
export const CONTEXT_MAX_TOKENS = 128_000;
