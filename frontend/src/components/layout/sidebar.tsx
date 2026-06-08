import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useUIStore, useAuthStore } from "@/stores";
import {
  LayoutDashboard,
  Activity,
  Bot,
  MessageSquare,
  Building2,
  ChevronLeft,
  User,
  Users,
  Sparkles,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";

/** 管理员导航项 */
const ADMIN_NAV_ITEMS = [
  { to: "/admin", icon: LayoutDashboard, label: "仪表盘" },
  { to: "/admin/observability", icon: Activity, label: "可观测性" },
  { to: "/admin/users", icon: Users, label: "用户管理" },
  { to: "/admin/agents", icon: Bot, label: "Agent管理" },
  { to: "/admin/skills", icon: Zap, label: "Skill管理" },
  { to: "/admin/conversations", icon: MessageSquare, label: "对话记录" },
  { to: "/admin/tenant", icon: Building2, label: "租户管理" },
  { to: "/profile", icon: User, label: "用户中心" },
];

/** 普通用户导航项 */
const USER_NAV_ITEMS = [
  { to: "/chat", icon: Sparkles, label: "开始对话" },
  { to: "/profile", icon: User, label: "用户中心" },
];

export function Sidebar() {
  const { sidebarOpen, toggleSidebar } = useUIStore();
  const { isAdmin } = useAuthStore();
  const location = useLocation();

  const navItems = isAdmin ? ADMIN_NAV_ITEMS : USER_NAV_ITEMS;

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r bg-background transition-all duration-300",
        sidebarOpen ? "w-64" : "w-16",
      )}
    >
      {/* Logo区域 */}
      <div className="flex h-14 items-center justify-between border-b px-4">
        {sidebarOpen && (
          <span className="text-lg font-bold text-primary">
            {isAdmin ? "ClipFlow" : "ClipFlow"}
          </span>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className={cn(!sidebarOpen && "mx-auto")}
        >
          <ChevronLeft
            className={cn(
              "h-4 w-4 transition-transform",
              !sidebarOpen && "rotate-180",
            )}
          />
        </Button>
      </div>

      {/* 导航菜单 */}
      <nav className="flex-1 space-y-1 p-2">
        {navItems.map(({ to, icon: Icon, label }) => {
          const isActive =
            to === "/admin"
              ? location.pathname === "/admin"
              : to === "/chat"
                ? location.pathname === "/chat"
                : location.pathname.startsWith(to);

          return (
            <NavLink
              key={to}
              to={to}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                "hover:bg-accent hover:text-accent-foreground",
                isActive
                  ? "bg-accent font-medium text-accent-foreground"
                  : "text-muted-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {sidebarOpen && <span>{label}</span>}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
