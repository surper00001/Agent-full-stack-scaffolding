import { useState, useCallback } from "react";

interface Toast {
  id: string;
  title?: string;
  description?: string;
  variant?: "default" | "destructive";
}

/**
 * Toast通知Hook — 轻量级全局通知管理
 * 使用方法: const { toast } = useToast()
 *          toast({ title: "成功", description: "操作已完成" })
 */
export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback(
    (props: Omit<Toast, "id">) => {
      const id = crypto.randomUUID();
      setToasts((prev) => [...prev, { id, ...props }]);

      // 3秒后自动移除
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 3000);
    },
    [],
  );

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, toast, dismiss };
}

// 全局单例Toast状态
let globalToast: ReturnType<typeof useToast> | null = null;

export function setGlobalToast(t: ReturnType<typeof useToast>) {
  globalToast = t;
}

export function getGlobalToast() {
  return globalToast;
}
