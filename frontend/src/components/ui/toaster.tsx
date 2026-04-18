import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "./toast";
import { useToast, setGlobalToast } from "./use-toast";

/**
 * 全局Toast渲染器 — 挂载到应用根组件
 */
export function Toaster() {
  const { toasts, dismiss } = useToast();

  // 挂载到全局以便在store/API层调用
  setGlobalToast({ toasts, toast: () => {}, dismiss });

  return (
    <ToastProvider>
      {toasts.map(({ id, title, description, variant }) => (
        <Toast
          key={id}
          variant={variant}
          onOpenChange={() => dismiss(id)}
        >
          <div className="grid gap-1">
            {title && <ToastTitle>{title}</ToastTitle>}
            {description && (
              <ToastDescription>{description}</ToastDescription>
            )}
          </div>
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
