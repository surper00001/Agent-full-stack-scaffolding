import { useEffect, useState, useCallback } from "react";
import { Outlet, useNavigate, useLocation, Link, Navigate } from "react-router-dom";
import { useAuth } from "@/hooks";
import { useAuthStore, useUIStore } from "@/stores";
import { useConversations } from "@/hooks";
import { useAgentStore } from "@/stores";
import { useConfirm } from "@/hooks/use-confirm";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Sparkles,
  MessageSquare,
  Plus,
  Trash2,
  User,
  LogOut,
  Sun,
  Moon,
  PanelLeftClose,
  PanelLeft,
  ChevronDown,
  Library,
} from "lucide-react";

/**
 * ChatLayout — 普通用户聊天布局
 *
 * 设计理念：像 ChatGPT 一样的聊天体验，不是管理后台。
 * 左侧：对话列表 + Agent 选择器
 * 右侧：完整聊天区域，无顶部导航栏
 */
export function ChatLayout() {
  const { isLoading, isAuthenticated } = useAuth(true);
  const { user, isAdmin, logout } = useAuthStore();
  const { sidebarOpen, toggleSidebar, theme, setTheme, colorTheme, setColorTheme } = useUIStore();
  const navigate = useNavigate();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  // 管理员禁止进入聊天界面，重定向到管理后台
  if (isAdmin) return <Navigate to="/admin" replace />;

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* 左侧对话面板 */}
      <ChatSidebar
        sidebarOpen={sidebarOpen}
        toggleSidebar={toggleSidebar}
        currentPath={location.pathname}
        currentSearch={location.search}
        onNavigate={(path) => navigate(path)}
      />

      {/* 右侧聊天区 — 无顶部 Header，全屏沉浸 */}
      <main className="flex flex-1 flex-col overflow-hidden">
        {/* 极简顶栏：仅主题切换 + 用户头像 */}
        <div className="flex h-11 items-center justify-end gap-1 border-b bg-background px-3 shrink-0">
          {/* 侧边栏切换 */}
          <Button variant="ghost" size="icon" className="h-7 w-7 mr-auto" onClick={toggleSidebar}>
            {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
          </Button>

          {/* 色系 */}
          <div className="flex items-center gap-0.5 mr-1">
            <button
              onClick={() => setColorTheme("emerald")}
              className={cn(
                "h-2.5 w-2.5 rounded-full border transition-all",
                colorTheme === "emerald"
                  ? "border-primary scale-125 bg-emerald-600"
                  : "border-muted-foreground/30 bg-emerald-400/80",
              )}
            />
            <button
              onClick={() => setColorTheme("amber")}
              className={cn(
                "h-2.5 w-2.5 rounded-full border transition-all",
                colorTheme === "amber"
                  ? "border-primary scale-125 bg-amber-500"
                  : "border-muted-foreground/30 bg-amber-400/80",
              )}
            />
          </div>

          {/* 明暗 */}
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          </Button>

          {/* 用户 */}
          {user && (
            <Link to="/profile" className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-accent transition-colors">
              <User className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground hidden sm:inline">{user.username}</span>
            </Link>
          )}

          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={logout}>
            <LogOut className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* 聊天内容区 — 无 padding，由子页面自行控制 */}
        <div className="flex-1 overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

/** 聊天侧边栏 — 对话历史 + Agent 选择 */
function ChatSidebar({
  sidebarOpen,
  toggleSidebar,
  currentPath,
  currentSearch,
  onNavigate,
}: {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  currentPath: string;
  currentSearch: string;
  onNavigate: (path: string) => void;
}) {
  const kbFromSearch = new URLSearchParams(currentSearch).get("kb");

  const navWithKb = useCallback(
    (path: string) => {
      if (kbFromSearch) {
        onNavigate(`${path}?kb=${encodeURIComponent(kbFromSearch)}`);
      } else {
        onNavigate(path);
      }
    },
    [kbFromSearch, onNavigate],
  );
  const { agents, fetchAgents } = useAgentStore();
  const { conversations, fetchConversations, createConversation, deleteConversation } = useConversations();
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const { user } = useAuthStore();
  const confirm = useConfirm();

  useEffect(() => {
    fetchAgents(1, 100);
    fetchConversations(1, 50);
  }, [fetchAgents, fetchConversations]);

  /** 新建对话并跳转 */
  const handleNewChat = useCallback(async () => {
    try {
      const agentType = agentFilter !== "all" ? agentFilter : undefined;
      const conv = await createConversation("新对话", agentType, kbFromSearch);
      navWithKb(`/chat/${conv.id}`);
    } catch {
      // ignore
    }
  }, [agentFilter, createConversation, kbFromSearch, navWithKb]);

  const handleDelete = useCallback(
    async (e: React.MouseEvent, convId: string) => {
      e.preventDefault();
      e.stopPropagation();
      if (!await confirm({ description: "确定删除该对话？", variant: "destructive" })) return;
      await deleteConversation(convId);
      if (currentPath === `/chat/${convId}`) {
        navWithKb("/chat");
      }
    },
    [deleteConversation, currentPath, navWithKb],
  );

  return (
    <aside
      className={cn(
        "flex h-full flex-col bg-muted/20 border-r transition-all duration-300",
        sidebarOpen ? "w-64" : "w-0 overflow-hidden border-r-0",
      )}
    >
      {/* Logo + 折叠按钮 */}
      <div className="flex h-11 items-center justify-between px-3 border-b">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <Sparkles className="h-4 w-4 text-primary" />
          ClipFlow
        </span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}>
          <PanelLeftClose className="h-4 w-4" />
        </Button>
      </div>

      {/* 导航菜单 */}
      <div className="px-3 py-1 space-y-0.5">
        <button
          onClick={() => navWithKb("/chat")}
          className={cn(
            "w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
            currentPath === "/chat" || currentPath.startsWith("/chat/")
              ? "bg-accent font-medium"
              : "text-muted-foreground hover:bg-accent/50",
          )}
        >
          <MessageSquare className="h-4 w-4" />
          对话
        </button>
        <button
          onClick={() => onNavigate("/kb")}
          className={cn(
            "w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
            currentPath.startsWith("/kb")
              ? "bg-accent font-medium"
              : "text-muted-foreground hover:bg-accent/50",
          )}
        >
          <Library className="h-4 w-4" />
          知识库
        </button>
      </div>

      {/* 新建对话 */}
      {currentPath.startsWith("/chat") && (
      <div className="p-2">
        <Button variant="outline" className="w-full justify-start gap-2 text-sm" onClick={handleNewChat}>
          <Plus className="h-4 w-4" />
          新对话
        </Button>
      </div>
      )}

      {/* Agent 选择器 + 对话列表（仅对话页面显示） */}
      {currentPath.startsWith("/chat") && (
      <>
        {agents.length > 0 && (
          <div className="px-3 py-1">
            <div className="relative">
              <select
                value={agentFilter}
                onChange={(e) => setAgentFilter(e.target.value)}
                className="w-full rounded-md border bg-background px-2 py-1.5 text-xs text-muted-foreground appearance-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="all">全部智能体</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.agent_type}>
                    {a.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
            </div>
          </div>
        )}

        <div className="app-scrollbar flex-1 overflow-y-auto px-2 py-1">
          {conversations.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground/60">
              暂无对话记录
            </p>
          ) : (
            <div className="space-y-0.5">
              {conversations.map((conv) => {
                const isActive = currentPath === `/chat/${conv.id}`;
                return (
                  <div key={conv.id} className="group relative">
                    <button
                      onClick={() => navWithKb(`/chat/${conv.id}`)}
                      className={cn(
                        "w-full flex items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors",
                        isActive
                          ? "bg-accent font-medium"
                          : "hover:bg-accent/50 text-muted-foreground",
                      )}
                    >
                      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate flex-1">{conv.title || "新对话"}</span>
                      <span className="text-[10px] text-muted-foreground/50 shrink-0">
                        {conv.message_count || 0}
                      </span>
                    </button>
                    <button
                      onClick={(e) => handleDelete(e, conv.id)}
                      className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/40 opacity-0 hover:text-destructive group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </>
      )}

      {/* KB 页面的 spacer */}
      {!currentPath.startsWith("/chat") && (
        <div className="flex-1" />
      )}

      {/* 底部用户信息 */}
      {user && (
        <Link
          to="/profile"
          className="flex items-center gap-2 border-t px-3 py-2.5 text-xs hover:bg-accent/50 transition-colors"
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary">
            <User className="h-3.5 w-3.5" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="truncate font-medium">{user.username}</p>
            <p className="text-[10px] text-muted-foreground">个人中心</p>
          </div>
        </Link>
      )}
    </aside>
  );
}
