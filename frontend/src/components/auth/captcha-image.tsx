import { ImageIcon } from "lucide-react";

interface CaptchaImageProps {
  src: string;
  hasError: boolean;
  onRefresh: () => void;
  onError: () => void;
  onLoad: () => void;
}

/** 验证码图片 — 按原始比例完整展示，避免被固定宽高裁切 */
export function CaptchaImage({
  src,
  hasError,
  onRefresh,
  onError,
  onLoad,
}: CaptchaImageProps) {
  if (hasError) {
    return (
      <button
        type="button"
        onClick={onRefresh}
        className="inline-flex h-11 min-w-[140px] items-center justify-center gap-1 rounded-md border border-border bg-muted/30 px-3 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ImageIcon className="h-4 w-4" />
        点击加载
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onRefresh}
      className="inline-flex shrink-0 items-center rounded-md border border-border bg-muted/30 p-1 transition-opacity hover:opacity-90"
      title="点击刷新验证码"
    >
      <img
        src={src}
        alt="验证码"
        className="block h-11 w-auto max-w-none cursor-pointer select-none"
        onError={onError}
        onLoad={onLoad}
        draggable={false}
      />
    </button>
  );
}
