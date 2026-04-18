import { useState, useEffect } from "react";

/**
 * 防抖Hook — 常用于搜索输入
 * @param value 原始值
 * @param delay 延迟毫秒数
 */
export function useDebounce<T>(value: T, delay = 300): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}
