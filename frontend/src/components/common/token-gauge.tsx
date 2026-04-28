import { useEffect, useState } from "react";

interface Props {
  used: number;
  quota: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export function TokenGauge({
  used,
  quota,
  size = 180,
  strokeWidth = 14,
  className = "",
}: Props) {
  const [animatedOffset, setAnimatedOffset] = useState(0);
  const percentage = quota > 0 ? Math.min(used / quota, 1) : 0;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - percentage);

  useEffect(() => {
    const timer = setTimeout(() => setAnimatedOffset(offset), 100);
    return () => clearTimeout(timer);
  }, [offset]);

  const center = size / 2;

  const color =
    percentage > 0.9 ? "var(--destructive)" : percentage > 0.7 ? "var(--chart-2)" : "var(--chart-1)";

  return (
    <div className={`flex flex-col items-center gap-3 ${className}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="var(--muted)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={animatedOffset}
          style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(0.4, 0, 0.2, 1)" }}
        />
      </svg>
      <div className="text-center">
        <div className="text-2xl font-bold" style={{ color }}>
          {Math.round(percentage * 100)}%
        </div>
        <div className="text-sm text-muted-foreground">
          {used.toLocaleString()} / {quota.toLocaleString()}
        </div>
      </div>
    </div>
  );
}
