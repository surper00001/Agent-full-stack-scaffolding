import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ChatLayout } from "@/components/layout/chat-layout";
import { MainLayout } from "@/components/layout/main-layout";
import { ErrorBoundary } from "@/components/common/error-boundary";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { useAuthStore } from "@/stores";

// 路由级代码分割 — 每个页面独立 chunk，首屏仅加载当前路由所需代码
const ChatHomePage = lazy(() => import("@/pages/chat"));
const ChatDetailPage = lazy(() => import("@/pages/chat/[id]"));
const ProfilePage = lazy(() => import("@/pages/profile"));
const KnowledgeBasesPage = lazy(() => import("@/pages/knowledge-bases"));
const KnowledgeBaseDetailPage = lazy(() => import("@/pages/knowledge-bases/[id]"));
const DocumentViewerPage = lazy(() => import("@/pages/knowledge-bases/[id]/documents/[docId]"));
const AdminDashboardPage = lazy(() => import("@/pages/admin/dashboard"));
const AdminAgentsPage = lazy(() => import("@/pages/admin/agents"));
const AdminAgentDetailPage = lazy(() => import("@/pages/admin/agents/[id]"));
const AdminConversationsPage = lazy(() => import("@/pages/admin/conversations"));
const AdminTenantPage = lazy(() => import("@/pages/admin/tenant"));
const AdminUsersPage = lazy(() => import("@/pages/admin/users"));
const AdminUserDetailPage = lazy(() => import("@/pages/admin/users/[id]"));
const AdminSkillsPage = lazy(() => import("@/pages/admin/skills"));
const AdminSkillDetailPage = lazy(() => import("@/pages/admin/skills/[id]"));
const AdminSkillNewPage = lazy(() => import("@/pages/admin/skills/new"));
const LoginPage = lazy(() => import("@/pages/login"));
const RegisterPage = lazy(() => import("@/pages/register"));
const NotFoundPage = lazy(() => import("@/pages/not-found"));

/** 页面加载中占位 — 与 MainLayout / ChatLayout 内边距对齐 */
function PageFallback() {
  return <LoadingSpinner size="lg" className="min-h-[60vh]" />;
}

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
      <Suspense fallback={<PageFallback />}>
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
      </Suspense>
    </ErrorBoundary>
  );
}
