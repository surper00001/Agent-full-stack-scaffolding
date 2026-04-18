import { http, HttpResponse } from "msw";

/** MSW请求处理器 — 模拟后端API响应 */
export const handlers = [
  // 登录
  http.post("/api/v1/auth/login", () => {
    return HttpResponse.json({
      success: true,
      message: "登录成功",
      data: {
        access_token: "mock-access-token",
        refresh_token: "mock-refresh-token",
        token_type: "bearer",
        expires_in: 3600,
      },
    });
  }),

  // 当前用户
  http.get("/api/v1/auth/me", () => {
    return HttpResponse.json({
      success: true,
      message: "",
      data: {
        id: "mock-user-id",
        tenant_id: "mock-tenant-id",
        email: "admin@example.com",
        name: "管理员",
        role: "admin",
        created_at: "2025-01-01T00:00:00Z",
      },
    });
  }),

  // Agent列表
  http.get("/api/v1/agents", () => {
    return HttpResponse.json({
      success: true,
      message: "",
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        pages: 0,
      },
    });
  }),
];
