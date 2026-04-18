import { Routes, Route } from "react-router-dom";
import { MainLayout } from "@/components/layout/main-layout";
import { ErrorBoundary } from "@/components/common/error-boundary";
import DashboardPage from "@/pages/dashboard";
import AgentsPage from "@/pages/agents";
import AgentDetailPage from "@/pages/agents/[id]";
import ConversationsPage from "@/pages/conversations";
import ConversationDetailPage from "@/pages/conversations/[id]";
import LoginPage from "@/pages/login";
import NotFoundPage from "@/pages/not-found";

/**
 * 应用路由配置
 * / → MainLayout（需要认证的页面组）
 *   / → 仪表盘
 *   /agents → Agent列表
 *   /agents/:id → Agent详情
 *   /conversations → 对话列表
 *   /conversations/:id → 对话详情
 * /login → 登录页（不需要认证）
 * * → 404
 */
export function AppRoutes() {
  return (
    <ErrorBoundary>
      <Routes>
        {/* 认证页面 */}
        <Route element={<MainLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:id" element={<AgentDetailPage />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route
            path="conversations/:id"
            element={<ConversationDetailPage />}
          />
        </Route>

        {/* 公开页面 */}
        <Route path="login" element={<LoginPage />} />

        {/* 404 */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </ErrorBoundary>
  );
}
