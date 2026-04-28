import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * 合并Tailwind类名 — shadcn/ui标准工具函数
 * clsx处理条件类名 + twMerge解决Tailwind类名冲突
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 规范化图形验证码输入：全角数字转半角，仅保留数字，最多 6 位 */
export function normalizeCaptchaCode(value: string): string {
  const halfWidth = value.replace(/[\uFF10-\uFF19]/g, (ch) =>
    String.fromCharCode(ch.charCodeAt(0) - 0xff10 + 0x30),
  );
  return halfWidth.replace(/\D/g, "").slice(0, 6);
}
