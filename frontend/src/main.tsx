import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// 初始化主题 — 从 localStorage 恢复
const root = document.documentElement;
const savedTheme = localStorage.getItem("theme") || "system";
const savedColor = (localStorage.getItem("colorTheme") as "emerald" | "amber") || "emerald";

root.setAttribute("data-theme", savedColor);
root.classList.remove("light", "dark");
if (savedTheme === "system") {
  root.classList.add(
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
} else {
  root.classList.add(savedTheme);
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
