import { create } from "zustand";

type ThemeMode = "light" | "dark" | "system";
type ColorTheme = "emerald" | "amber";

interface UIStore {
  sidebarOpen: boolean;
  theme: ThemeMode;
  colorTheme: ColorTheme;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setTheme: (theme: ThemeMode) => void;
  setColorTheme: (theme: ColorTheme) => void;
}

function applyTheme(theme: ThemeMode) {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  if (theme === "system") {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.classList.add(prefersDark ? "dark" : "light");
  } else {
    root.classList.add(theme);
  }
}

function applyColorTheme(colorTheme: ColorTheme) {
  document.documentElement.setAttribute("data-theme", colorTheme);
}

export const useUIStore = create<UIStore>((set) => ({
  sidebarOpen: true,
  theme: (localStorage.getItem("theme") as ThemeMode) || "system",
  colorTheme: (localStorage.getItem("colorTheme") as ColorTheme) || "emerald",

  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),

  setTheme: (theme: ThemeMode) => {
    localStorage.setItem("theme", theme);
    applyTheme(theme);
    set({ theme });
  },

  setColorTheme: (colorTheme: ColorTheme) => {
    localStorage.setItem("colorTheme", colorTheme);
    applyColorTheme(colorTheme);
    set({ colorTheme });
  },
}));
