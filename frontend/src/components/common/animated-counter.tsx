import { useEffect, useState } from "react";

interface Props {
  value: number;
  duration?: number;
  className?: string;
  formatter?: (v: number) => string;
}

export function AnimatedCounter({ value, duration = 800, className, formatter }: Props) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (value === display) return;
    const start = performance.now();
    const from = display;

    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(from + (value - from) * eased);
      setDisplay(current);
      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }

    requestAnimationFrame(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <span className={className}>
      {formatter ? formatter(display) : display.toLocaleString()}
    </span>
  );
}
