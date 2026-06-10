import { DollarSign } from "lucide-react";
import { formatCost } from "@/lib/cost";

interface CostBadgeProps {
  cost: number;
  size?: "sm" | "md";
}

export function CostBadge({ cost, size: _size = "sm" }: CostBadgeProps) {
  return (
    <span
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800"
      title={`预估 API 费用: ${formatCost(cost)}`}
    >
      <DollarSign className="h-2.5 w-2.5" />
      {formatCost(cost)}
    </span>
  );
}
