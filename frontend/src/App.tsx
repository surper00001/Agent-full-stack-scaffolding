import { AppRoutes } from "@/routes";
import { Toaster } from "@/components/ui/toaster";
import { ConfirmProvider } from "@/hooks/use-confirm";

/**
 * 应用根组件
 * 全局Provider在此组装：路由、确认对话框、Toast通知等
 */
function App() {
  return (
    <ConfirmProvider>
      <AppRoutes />
      <Toaster />
    </ConfirmProvider>
  );
}

export default App;
