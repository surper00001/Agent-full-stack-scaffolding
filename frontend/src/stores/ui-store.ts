import { create } from "zustand";

type Theme = "light" | "dark" | "system";

interface UIStore {
  sidebarOpen: boolean;
  theme: Theme;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setTheme: (theme: Theme) => void;
}

/**
 * UI全局状态
 * 管理侧边栏展开/收起、主题切换等UI层面的全局状态
 */
export const useUIStore = create<UIStore>((set) => ({
  sidebarOpen: true,
  theme: (localStorage.getItem("theme") as Theme) || "system",

  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),
  setTheme: (theme: Theme) => {
    localStorage.setItem("theme", theme);
    // 将主题类名应用到html根元素
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    if (theme === "system") {
      const prefersDark = window.matchMedia(
        "(prefers-color-scheme: dark)",
      ).matches;
      root.classList.add(prefersDark ? "dark" : "light");
    } else {
      root.classList.add(theme);
    }
    set({ theme });
  },
}));
