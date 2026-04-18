import { useAuthStore, useUIStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Moon, Sun, LogOut, User } from "lucide-react";

/**
 * 顶部导航栏
 * 包含：主题切换、用户信息、登出按钮
 */
export function Header() {
  const { user, logout } = useAuthStore();
  const { theme, setTheme } = useUIStore();

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  return (
    <header className="flex h-14 items-center justify-between border-b bg-background px-6">
      <div>
        <h2 className="text-sm font-medium text-muted-foreground">
          AI Agent 管理平台
        </h2>
      </div>

      <div className="flex items-center gap-3">
        {/* 主题切换 */}
        <Button variant="ghost" size="icon" onClick={toggleTheme}>
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>

        {/* 用户信息 */}
        {user && (
          <div className="flex items-center gap-2 text-sm">
            <User className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">{user.name}</span>
          </div>
        )}

        {/* 登出 */}
        <Button variant="ghost" size="icon" onClick={logout}>
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
