import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface ConfirmOptions {
  title?: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
}

interface ConfirmState extends ConfirmOptions {
  resolve: (value: boolean) => void;
}

const ConfirmContext = createContext<(opts: ConfirmOptions) => Promise<boolean>>(() =>
  Promise.resolve(false),
);

/** 全局确认对话框 Provider — 替代 window.confirm() */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConfirmState | null>(null);

  const confirm = useCallback(
    (opts: ConfirmOptions): Promise<boolean> =>
      new Promise((resolve) => {
        setState({ ...opts, resolve });
      }),
    [],
  );

  const handleClose = (value: boolean) => {
    if (state) {
      state.resolve(value);
      setState(null);
    }
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AlertDialog open={!!state} onOpenChange={(open) => !open && handleClose(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{state?.title ?? "确认操作"}</AlertDialogTitle>
            <AlertDialogDescription>{state?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => handleClose(false)}>
              {state?.cancelText ?? "取消"}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => handleClose(true)}
              className={
                state?.variant === "destructive" ? "bg-destructive hover:bg-destructive/90" : ""
              }
            >
              {state?.confirmText ?? "确定"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext.Provider>
  );
}

/** 程序化确认对话框 Hook — 用法：const confirmed = await confirm({ description: "确定删除？" }) */
export function useConfirm() {
  return useContext(ConfirmContext);
}
