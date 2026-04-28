import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores";
import { LoginBrand } from "./login-brand";
import { LoginForm } from "./login-form";

export default function LoginPage() {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  const handleSubmit = async (account: string, password: string, code: string) => {
    setError(null);
    setIsSubmitting(true);
    try {
      await login({ account, password, code });
      navigate("/", { replace: true });
    } catch (err) {
      const msg = (err as { userMessage?: string })?.userMessage
        || (err as Error)?.message
        || "登录失败，请检查账号和密码";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-background">
      {/* 左侧品牌区 — 隐藏于小屏 */}
      <div className="hidden lg:flex lg:w-5/12 xl:w-1/2">
        <LoginBrand />
      </div>

      {/* 右侧表单区 */}
      <div className="flex w-full items-center justify-center lg:w-7/12 xl:w-1/2">
        <LoginForm
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          error={error}
        />
      </div>
    </div>
  );
}
