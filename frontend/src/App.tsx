import { AppRoutes } from "@/routes";
import { Toaster } from "@/components/ui/toaster";

/**
 * 应用根组件
 * 全局Provider在此组装：路由、Toast通知等
 */
function App() {
  return (
    <>
      <AppRoutes />
      <Toaster />
    </>
  );
}

export default App;
