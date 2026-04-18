// 应用级常量配置

/** Vite环境变量类型声明 */
/// <reference types="vite/client" />

/** API基础路径 — 开发时通过Vite代理转发，生产时同源部署 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

/** 认证Token存储键名 */
export const AUTH_TOKEN_KEY = "agent_platform_token";

/** 刷新Token存储键名 */
export const REFRESH_TOKEN_KEY = "agent_platform_refresh";

/** 分页默认大小 */
export const DEFAULT_PAGE_SIZE = 20;

/** 请求超时时间（毫秒） */
export const REQUEST_TIMEOUT = 30000;
