import { useEffect } from "react";
import { useAuthStore } from "@/stores";
import { useNavigate } from "react-router-dom";

/**
 * 认证Hook — 页面级认证守卫
 * requireAuth=true 时未登录自动跳转登录页
 */
export function useAuth(requireAuth = true) {
  const { user, isAuthenticated, isLoading, initAuth } = useAuthStore();
  const navigate = useNavigate();

  useEffect(() => {
    initAuth();
  }, [initAuth]);

  useEffect(() => {
    if (!isLoading && requireAuth && !isAuthenticated) {
      navigate("/login", { replace: true });
    }
  }, [isLoading, isAuthenticated, requireAuth, navigate]);

  return { user, isAuthenticated, isLoading };
}
