import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { DollarSign } from "lucide-react";
import { formatCost } from "@/lib/cost";

interface DailyCost {
  date: string;
  cost: number;
}

interface CostTrendChartProps {
  data: DailyCost[];
  title?: string;
}

export function CostTrendChart({ data, title = "费用趋势" }: CostTrendChartProps) {
  const totalCost = data.reduce((sum, d) => sum + d.cost, 0);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-amber-500" />
            {title}
          </CardTitle>
          <span className="text-xs font-mono text-amber-600 font-medium">
            合计 {formatCost(totalCost)}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v.toFixed(2)}`} />
            <Tooltip
              formatter={(value: number) => [formatCost(value), "费用"]}
              labelFormatter={(label) => `日期: ${label}`}
            />
            <Bar dataKey="cost" radius={[3, 3, 0, 0]} maxBarSize={40}>
              {data.map((entry, index) => (
                <Cell
                  key={index}
                  fill={entry.cost > 0.5 ? "#f59e0b" : entry.cost > 0.1 ? "#fbbf24" : "#fde68a"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
