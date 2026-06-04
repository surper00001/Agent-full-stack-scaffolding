import { Navigate, Route, Routes } from "react-router-dom";
import { ChatLayout } from "@/components/layout/chat-layout";
import { MainLayout } from "@/components/layout/main-layout";
import { ErrorBoundary } from "@/components/common/error-boundary";
import { useAuthStore } from "@/stores";
import ChatHomePage from "@/pages/chat";
import ChatDetailPage from "@/pages/chat/[id]";
import ProfilePage from "@/pages/profile";
import KnowledgeBasesPage from "@/pages/knowledge-bases";
import KnowledgeBaseDetailPage from "@/pages/knowledge-bases/[id]";
import DocumentViewerPage from "@/pages/knowledge-bases/[id]/documents/[docId]";
import AdminDashboardPage from "@/pages/admin/dashboard";
import AdminAgentsPage from "@/pages/admin/agents";
import AdminAgentDetailPage from "@/pages/admin/agents/[id]";
import AdminConversationsPage from "@/pages/admin/conversations";
import AdminTenantPage from "@/pages/admin/tenant";
import AdminUsersPage from "@/pages/admin/users";
import AdminUserDetailPage from "@/pages/admin/users/[id]";
import AdminSkillsPage from "@/pages/admin/skills";
import AdminSkillDetailPage from "@/pages/admin/skills/[id]";
import AdminSkillNewPage from "@/pages/admin/skills/new";
import LoginPage from "@/pages/login";
import RegisterPage from "@/pages/register";
import NotFoundPage from "@/pages/not-found";

/** 按角色重定向首页：管理员 → /admin，普通用户 → /chat */
function RoleRedirect() {
  const { isAdmin } = useAuthStore();
  return <Navigate to={isAdmin ? "/admin" : "/chat"} replace />;
}

/** 管理员路由守卫 — 非管理员重定向到聊天页 */
function AdminGuard() {
  const { isAdmin } = useAuthStore();
  if (!isAdmin) return <Navigate to="/chat" replace />;
  return <MainLayout />;
}

export function AppRoutes() {
  return (
    <ErrorBoundary>
      <Routes>
        {/* 普通用户 — 聊天布局，像 ChatGPT 一样沉浸式 */}
        <Route element={<ChatLayout />}>
          <Route index element={<RoleRedirect />} />
          <Route path="chat" element={<ChatHomePage />} />
          <Route path="chat/:id" element={<ChatDetailPage />} />
          <Route path="kb" element={<KnowledgeBasesPage />} />
          <Route path="kb/:id" element={<KnowledgeBaseDetailPage />} />
          <Route path="kb/:id/documents/:docId" element={<DocumentViewerPage />} />
          <Route path="profile" element={<ProfilePage />} />
        </Route>

        {/* 管理员 — 管理后台布局 */}
        <Route element={<AdminGuard />}>
          <Route path="admin" element={<AdminDashboardPage />} />
          <Route path="admin/agents" element={<AdminAgentsPage />} />
          <Route path="admin/agents/:id" element={<AdminAgentDetailPage />} />
          <Route path="admin/conversations" element={<AdminConversationsPage />} />
          <Route path="admin/tenant" element={<AdminTenantPage />} />
          <Route path="admin/users" element={<AdminUsersPage />} />
          <Route path="admin/users/:id" element={<AdminUserDetailPage />} />
          <Route path="admin/skills" element={<AdminSkillsPage />} />
          <Route path="admin/skills/new" element={<AdminSkillNewPage />} />
          <Route path="admin/skills/:id" element={<AdminSkillDetailPage />} />
        </Route>

        {/* 公开页面 */}
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />

        {/* 404 */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </ErrorBoundary>
  );
}
