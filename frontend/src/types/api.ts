// API通用响应类型

/** 统一API响应包装 */
export interface ApiResponse<T> {
  data: T;
  message: string;
  success: boolean;
}

/** 分页请求参数 */
export interface PaginationParams {
  page: number;
  page_size: number;
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** API错误类型 */
export interface ApiError {
  code: string;
  message: string;
  detail?: Record<string, string[]>;
}
