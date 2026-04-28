import { Outlet } from "react-router-dom";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { useAuth } from "@/hooks";

/**
 * 主布局 — 认证守卫 + 侧边栏 + 顶部导航 + 内容区
 * 所有认证页面（/dashboard, /agents 等）都在此布局内渲染
 */
export function MainLayout() {
  const { isLoading, isAuthenticated } = useAuth(true);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="app-scrollbar flex min-h-0 flex-1 flex-col overflow-hidden bg-muted/30 p-6">
          <div className="app-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
