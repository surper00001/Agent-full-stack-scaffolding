import { useState, useCallback, useRef, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, Mail, Lock, ArrowRight, RefreshCw, Shield, AlertCircle, Film } from "lucide-react";
import { CaptchaImage } from "@/components/auth/captcha-image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn, normalizeCaptchaCode } from "@/lib/utils";
import { API_BASE_URL } from "@/lib/constants";

interface Props {
  onSubmit: (account: string, password: string, code: string) => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
}

export function LoginForm({ onSubmit, isSubmitting, error }: Props) {
  const navigate = useNavigate();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [shakingField, setShakingField] = useState<string | null>(null);
  const [captchaKey, setCaptchaKey] = useState(0);
  const [captchaError, setCaptchaError] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const accountRef = useRef<HTMLInputElement>(null);

  const captchaTarget = account.trim() || "default";
  const captchaUrl = `${API_BASE_URL}/auth/captcha?target=${encodeURIComponent(captchaTarget)}&t=${captchaKey}`;

  const refreshCaptcha = useCallback(() => {
    setCaptchaKey((k) => k + 1);
    setCode("");
    setCaptchaError(false);
  }, []);

  const triggerShake = (field: string) => {
    setShakingField(field);
    setTimeout(() => setShakingField(null), 500);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;

    if (!account.trim()) {
      setLocalError("请输入账号");
      triggerShake("account");
      accountRef.current?.focus();
      return;
    }
    if (!password) {
      setLocalError("请输入密码");
      triggerShake("password");
      return;
    }
    const normalizedCode = normalizeCaptchaCode(code);
    if (normalizedCode.length !== 6) {
      setLocalError("请输入 6 位验证码");
      triggerShake("code");
      return;
    }
    setLocalError(null);
    try {
      await onSubmit(account, password, normalizedCode);
    } catch {
      triggerShake("form");
      refreshCaptcha();
    }
  };

  return (
    <div className="flex w-full flex-col justify-center p-8 sm:p-10 lg:p-14">
      <div className="mx-auto w-full max-w-[400px]">
        {/* Mobile logo */}
        <div className="mb-8 flex items-center justify-center gap-2 lg:hidden">
          <Film className="h-6 w-6 text-zinc-700 dark:text-zinc-300" />
          <span className="text-lg font-semibold tracking-tight">ClipFlow</span>
        </div>

        {/* Header */}
        <div className="mb-10">
          <h2 className="text-2xl font-bold tracking-tight text-foreground">登录</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            欢迎回到 ClipFlow 视频创作工作台
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5" noValidate>
          {/* Account */}
          <InputField
            id="account"
            label="账号"
            placeholder="用户名 / 邮箱 / 手机号"
            icon={Mail}
            value={account}
            onChange={(v) => { setAccount(v); setLocalError(null); }}
            shaking={shakingField === "account"}
            ref={accountRef}
            autoFocus
            autoComplete="username"
          />

          {/* Password */}
          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium text-foreground">
              密码
            </label>
            <div className={cn("relative", shakingField === "password" && "animate-shake")}>
              <Lock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/50" />
              <Input
                id="password"
                type={showPw ? "text" : "password"}
                placeholder="输入密码"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setLocalError(null); }}
                className="h-11 pl-10 pr-10"
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/50 hover:text-foreground transition-colors"
                tabIndex={-1}
              >
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Captcha */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              验证码
            </label>
            <div className="flex items-start gap-3">
              <CaptchaImage
                src={captchaUrl}
                hasError={captchaError}
                onRefresh={refreshCaptcha}
                onError={() => setCaptchaError(true)}
                onLoad={() => setCaptchaError(false)}
              />
              <button
                type="button"
                onClick={refreshCaptcha}
                className="mt-1 shrink-0 rounded-lg p-2 hover:bg-muted transition-colors"
                title="刷新验证码"
              >
                <RefreshCw className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
            <div className={cn("relative", shakingField === "code" && "animate-shake")}>
              <Shield className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/50" />
              <Input
                placeholder="图片中的 6 位数字"
                value={code}
                onChange={(e) => { setCode(normalizeCaptchaCode(e.target.value)); setLocalError(null); }}
                inputMode="numeric"
                maxLength={6}
                className="h-11 pl-10 font-mono tracking-[0.3em]"
                autoComplete="off"
              />
            </div>
          </div>

          {/* Error */}
          {(localError || error) && (
            <div className={cn(
              "flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2.5 text-sm text-destructive",
              shakingField === "form" && "animate-shake",
            )}>
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{localError || error}</span>
            </div>
          )}

          {/* Submit */}
          <Button
            type="submit"
            className="h-11 w-full text-sm font-semibold bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100 transition-all active:scale-[0.98]"
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <span className="flex items-center gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                验证中...
              </span>
            ) : (
              <span className="flex items-center gap-2">
                登录
                <ArrowRight className="h-4 w-4" />
              </span>
            )}
          </Button>

          {/* Register */}
          <p className="text-center text-sm text-muted-foreground">
            还没有账户？
            <button
              type="button"
              onClick={() => navigate("/register")}
              className="ml-1 font-medium text-foreground hover:underline"
            >
              立即注册
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}

/** Controlled input with icon */
import { forwardRef } from "react";

interface InputFieldProps {
  id: string;
  label: string;
  placeholder: string;
  icon: React.ElementType;
  value: string;
  onChange: (value: string) => void;
  shaking: boolean;
  autoFocus?: boolean;
  autoComplete?: string;
}

const InputField = forwardRef<HTMLInputElement, InputFieldProps>(
  function InputField({ id, label, placeholder, icon: Icon, value, onChange, shaking, autoFocus, autoComplete }, ref) {
    return (
      <div className="space-y-2">
        <label htmlFor={id} className="text-sm font-medium text-foreground">{label}</label>
        <div className={cn("relative", shaking && "animate-shake")}>
          <Icon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/50" />
          <Input
            ref={ref}
            id={id}
            placeholder={placeholder}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="h-11 pl-10"
            autoFocus={autoFocus}
            autoComplete={autoComplete}
          />
        </div>
      </div>
    );
  }
);
