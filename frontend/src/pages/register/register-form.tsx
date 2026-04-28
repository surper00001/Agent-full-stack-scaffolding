import { useState, useCallback, useEffect, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, User, Mail, Phone, KeyRound, RefreshCw, ArrowRight, CheckCircle } from "lucide-react";
import { CaptchaImage } from "@/components/auth/captcha-image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as authApi from "@/api/auth";
import { cn, normalizeCaptchaCode } from "@/lib/utils";
import { API_BASE_URL } from "@/lib/constants";

export function RegisterForm() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [captchaKey, setCaptchaKey] = useState(0);
  const [captchaError, setCaptchaError] = useState(false);
  const [done, setDone] = useState(false);

  // 与后端 Redis key 一致：邮箱优先，其次手机号
  const captchaTarget = email.trim() || phone.trim();
  const [debouncedTarget, setDebouncedTarget] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedTarget(captchaTarget), 400);
    return () => clearTimeout(timer);
  }, [captchaTarget]);

  const captchaUrl = debouncedTarget
    ? `${API_BASE_URL}/auth/captcha?target=${encodeURIComponent(debouncedTarget)}&t=${captchaKey}`
    : "";

  // 邮箱/手机变更后刷新验证码，避免填码后改账号导致校验失败
  useEffect(() => {
    if (!debouncedTarget) return;
    setCaptchaKey((k) => k + 1);
    setCode("");
  }, [debouncedTarget]);

  const refreshCaptcha = useCallback(() => {
    setCaptchaKey((k) => k + 1);
    setCode("");
    setCaptchaError(false);
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError("请填写用户名和密码");
      return;
    }
    if (!email && !phone) {
      setError("请填写邮箱或手机号");
      return;
    }
    const normalizedCode = normalizeCaptchaCode(code);
    if (normalizedCode.length !== 6) {
      setError(
        code.trim().length > 0
          ? "验证码须为 6 位数字（请使用半角 0-9）"
          : "请输入 6 位验证码",
      );
      return;
    }
    setError(null);
    setIsSubmitting(true);
    try {
      await authApi.register({
        username,
        password,
        code: normalizedCode,
        email: email || undefined,
        phone: phone || undefined,
      });
      setDone(true);
    } catch (err) {
      setError((err as { userMessage?: string }).userMessage || (err as Error).message || "注册失败，请重试");
      refreshCaptcha();
    } finally {
      setIsSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="flex flex-col items-center text-center animate-scale-in p-8 lg:p-12">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-chart-3/20 mb-5">
          <CheckCircle className="h-7 w-7 text-chart-1" />
        </div>
        <h3 className="text-xl font-bold mb-2">注册成功</h3>
        <p className="text-muted-foreground mb-6">欢迎加入 ClipFlow，请登录以继续</p>
        <Button onClick={() => navigate("/login")} className="w-full">
          <ArrowRight className="h-4 w-4 mr-1" />前往登录
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col justify-center p-8 lg:p-12 animate-fade-in-up">
      <div className="mx-auto w-full max-w-sm">
        <h2 className="text-2xl font-bold tracking-tight mb-1">创建账户</h2>
        <p className="text-muted-foreground mb-8">加入 AI 短视频创作平台</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field icon={User} label="用户名" required>
            <Input
              placeholder="输入用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={2}
              maxLength={50}
              className="pl-10"
            />
          </Field>

          <Field icon={Mail} label="邮箱">
            <Input
              type="email"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="pl-10"
            />
          </Field>

          <Field icon={Phone} label="手机号（选填）">
            <Input
              placeholder="13800138000"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="pl-10"
            />
          </Field>

          <Field icon={Lock} label="密码" required>
            <Input
              type="password"
              placeholder="至少6位"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="pl-10"
            />
          </Field>

          {/* 图形验证码 — 始终可见 */}
          <div className="space-y-2">
            <label className="text-sm font-medium">
              验证码<span className="text-destructive ml-0.5">*</span>
            </label>
            <div className="flex items-center gap-3">
              {!debouncedTarget ? (
                <div className="inline-flex h-11 min-w-[140px] items-center justify-center rounded-md border border-border bg-muted/30 px-3 text-center text-xs text-muted-foreground">
                  先填邮箱或手机
                </div>
              ) : (
                <CaptchaImage
                  src={captchaUrl}
                  hasError={captchaError}
                  onRefresh={refreshCaptcha}
                  onError={() => setCaptchaError(true)}
                  onLoad={() => setCaptchaError(false)}
                />
              )}
              <button
                type="button"
                onClick={refreshCaptcha}
                className="shrink-0 p-1.5 rounded-md hover:bg-muted transition-colors"
                title="刷新验证码"
              >
                <RefreshCw className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
          </div>

          <Field icon={KeyRound} label="">
            <Input
              placeholder="输入图片中的6位验证码"
              value={code}
              onChange={(e) => setCode(normalizeCaptchaCode(e.target.value))}
              inputMode="numeric"
              required
              maxLength={6}
              className="pl-10 tracking-widest"
              autoComplete="off"
              disabled={!debouncedTarget}
            />
          </Field>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "注册中..." : "注册"}
          </Button>

          <p className="text-center text-sm text-muted-foreground">
            已有账户？
            <button
              type="button"
              onClick={() => navigate("/login")}
              className="ml-1 text-violet-600 hover:underline font-medium dark:text-violet-400"
            >
              去登录
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}

function Field({
  icon: Icon,
  label,
  children,
  className,
  required,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
  className?: string;
  required?: boolean;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {label ? (
        <label className="text-sm font-medium">
          {label}{required && <span className="text-destructive ml-0.5">*</span>}
        </label>
      ) : null}
      <div className="relative">
        <Icon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        {children}
      </div>
    </div>
  );
}
