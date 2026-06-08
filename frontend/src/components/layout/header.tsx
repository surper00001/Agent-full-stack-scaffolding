import { useState, useEffect } from "react";
import { useAuthStore, useUIStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Moon, Sun, LogOut, User, Palette, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Link } from "react-router-dom";
import { GlobalSearch } from "@/components/common/global-search";

export function Header() {
  const { user, isAdmin, logout } = useAuthStore();
  const { theme, setTheme, colorTheme, setColorTheme } = useUIStore();
  const [searchOpen, setSearchOpen] = useState(false);

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  const toggleColor = () => {
    setColorTheme(colorTheme === "emerald" ? "amber" : "emerald");
  };

  // Ctrl+K keyboard shortcut for global search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <header className="flex h-14 items-center justify-between border-b bg-background px-6">
      <div className="flex items-center gap-4">
        <h2 className="text-sm font-medium text-muted-foreground">
          {isAdmin ? "ClipFlow 管理后台" : "ClipFlow"}
        </h2>
      </div>

      <div className="flex items-center gap-2">
        {/* 色系切换 */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleColor}
          title={colorTheme === "emerald" ? "切换至琥珀主题" : "切换至翡翠主题"}
        >
          <Palette className="h-4 w-4" />
          <span className="sr-only">切换色系</span>
        </Button>

        {/* 色系指示点 */}
        <div className="flex items-center gap-1 mr-1">
          <button
            onClick={() => setColorTheme("emerald")}
            className={cn(
              "h-3 w-3 rounded-full border-2 transition-all",
              colorTheme === "emerald"
                ? "border-primary scale-110 bg-emerald-600"
                : "border-muted-foreground/30 bg-emerald-400/80",
            )}
          />
          <button
            onClick={() => setColorTheme("amber")}
            className={cn(
              "h-3 w-3 rounded-full border-2 transition-all",
              colorTheme === "amber"
                ? "border-primary scale-110 bg-amber-500"
                : "border-muted-foreground/30 bg-amber-400/80",
            )}
          />
        </div>

        {/* 全局搜索 */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setSearchOpen(true)}
          className="gap-2 text-muted-foreground"
        >
          <Search className="h-4 w-4" />
          <span className="hidden lg:inline">搜索...</span>
          <kbd className="hidden sm:inline-flex h-5 items-center gap-0.5 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
            Ctrl+K
          </kbd>
        </Button>

        {/* 明暗切换 */}
        <Button variant="ghost" size="icon" onClick={toggleTheme}>
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>

        {/* 用户信息及链接 */}
        {user && (
          <Link
            to="/profile"
            className="flex items-center gap-2 text-sm rounded-md px-2 py-1 hover:bg-accent transition-colors"
          >
            <User className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground hidden sm:inline">{user.username}</span>
            {isAdmin && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
                管理员
              </span>
            )}
          </Link>
        )}

        {/* 登出 */}
        <Button variant="ghost" size="icon" onClick={logout}>
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </header>
  );
}
