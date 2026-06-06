import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";
import {
  AUTH_TOKEN_KEY,
  API_BASE_URL,
  REFRESH_TOKEN_KEY,
  REQUEST_TIMEOUT,
} from "@/lib/constants";

/**
 * Axios实例 — 全局HTTP客户端
 * 包含：请求拦截（注入Token）、响应拦截（401自动刷新、统一错误处理）、
 * GET 请求去重（in-flight dedup）
 */

// 刷新Token锁 — 防止并发401同时刷新
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

/** 处理排队请求 */
function processQueue(error: unknown, token: string | null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error);
    } else {
      resolve(token!);
    }
  });
  failedQueue = [];
}

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT,
  headers: { "Content-Type": "application/json" },
});

// ===== 请求拦截器 =====
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // FormData 上传须由浏览器设置 multipart boundary，不能沿用默认 application/json
  if (config.data instanceof FormData && config.headers) {
    config.headers.delete("Content-Type");
  }

  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ===== 响应拦截器 =====
client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // 401 — 尝试用refresh_token换新token
    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
      if (!refreshToken) {
        // 无refresh token，直接跳转登录
        localStorage.removeItem(AUTH_TOKEN_KEY);
        window.location.href = "/login";
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // 已有刷新进行中，将当前请求加入排队
        return new Promise<string>((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return client(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const { data } = await axios.post(
          `${API_BASE_URL}/auth/refresh`,
          { refresh_token: refreshToken },
        );
        const newToken = data.data.access_token;
        const newRefreshToken = data.data.refresh_token;

        localStorage.setItem(AUTH_TOKEN_KEY, newToken);
        localStorage.setItem(REFRESH_TOKEN_KEY, newRefreshToken);

        processQueue(null, newToken);

        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return client(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        // 刷新失败 — 清除认证信息
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
        window.location.href = "/login";
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    // 其他错误 — 统一提取消息
    const message =
      (error.response?.data as { message?: string })?.message ||
      error.message ||
      "网络请求失败";

    return Promise.reject({ ...error, userMessage: message });
  },
);

export default client;

// ── GET 请求去重 ──

/** In-flight GET 请求映射表 — key → Promise */
const _inflightGets = new Map<string, Promise<unknown>>();

/**
 * 带去重的 GET 请求：同一 URL+params 的并发请求自动复用结果。
 *
 * 用法（替代 client.get）:
 *   const { data } = await dedupedGet<User[]>("/api/v1/users", { params: { page: 1 } });
 */
export async function dedupedGet<T = unknown>(
  url: string,
  config?: Record<string, unknown>,
): Promise<{ data: T }> {
  const key = `${url}::${JSON.stringify(config || {})}`;

  const existing = _inflightGets.get(key);
  if (existing) {
    return existing as Promise<{ data: T }>;
  }

  const promise = client
    .get<T>(url, config)
    .then((res) => ({ data: res.data }))
    .finally(() => {
      _inflightGets.delete(key);
    });

  // 防止内存泄漏：Map 最大 50 条
  if (_inflightGets.size >= 50) {
    const firstKey = _inflightGets.keys().next().value;
    if (firstKey) _inflightGets.delete(firstKey);
  }
  _inflightGets.set(key, promise);

  return promise;
}
