import { useState } from "react";

interface DataPoint {
  label: string;
  value: number;
}

interface Props {
  data: DataPoint[];
  height?: number;
  className?: string;
}

export function BarChart({ data, height = 160, className = "" }: Props) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const maxVal = Math.max(...data.map((d) => d.value), 1);
  const barWidth = Math.max((data.length > 0 ? 100 / data.length : 0) - 2, 2);

  return (
    <div className={`relative ${className}`}>
      <svg
        width="100%"
        height={height + 24}
        viewBox={`0 0 ${data.length * 10} ${height + 24}`}
        preserveAspectRatio="none"
        className="w-full"
      >
        {data.map((d, i) => {
          const barH = Math.max((d.value / maxVal) * height, d.value > 0 ? 3 : 0);
          const x = i * 10 + (10 - barWidth) / 2;
          const y = height - barH;
          const isHovered = hoveredIdx === i;

          return (
            <g key={d.label}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barH}
                rx={1.5}
                fill={isHovered ? "var(--primary)" : "var(--chart-3)"}
                style={{ transition: "fill 0.15s ease" }}
                onMouseEnter={() => setHoveredIdx(i)}
                onMouseLeave={() => setHoveredIdx(null)}
              />
              {isHovered && (
                <g>
                  <rect
                    x={x - 8}
                    y={y - 22}
                    width={barWidth + 16}
                    height={18}
                    rx={4}
                    fill="var(--foreground)"
                    opacity={0.9}
                  />
                  <text
                    x={x + barWidth / 2}
                    y={y - 9}
                    textAnchor="middle"
                    fill="var(--primary-foreground)"
                    fontSize="8"
                  >
                    {d.value.toLocaleString()}
                  </text>
                  <line
                    x1={x}
                    y1={y}
                    x2={x + barWidth}
                    y2={y}
                    stroke="var(--primary)"
                    strokeWidth={1.5}
                    strokeLinecap="round"
                  />
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between px-1 text-[10px] text-muted-foreground mt-1">
        {data.length > 0 && (
          <>
            <span>{data[0].label}</span>
            <span>{data[Math.floor(data.length / 2)].label}</span>
            <span>{data[data.length - 1].label}</span>
          </>
        )}
      </div>
    </div>
  );
}
