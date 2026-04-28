import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { UsageRecord } from "@/types";

interface Props {
  records: UsageRecord[];
}

export function UsageHistory({ records }: Props) {
  if (records.length === 0) {
    return null;
  }

  return (
    <Card className="animate-fade-in-up" style={{ animationDelay: "560ms", animationFillMode: "backwards" }}>
      <CardHeader>
        <CardTitle className="text-base">最近用量记录</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="text-left font-medium px-6 py-3 w-1/3">日期</th>
              <th className="text-left font-medium px-6 py-3 w-1/3">Agent</th>
              <th className="text-right font-medium px-6 py-3 w-1/3">Token 消耗</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r, i) => (
              <tr
                key={i}
                className="border-b last:border-b-0 transition-colors hover:bg-muted/50"
              >
                <td className="px-6 py-3 text-muted-foreground">{r.date}</td>
                <td className="px-6 py-3">{r.agentName}</td>
                <td className="px-6 py-3 text-right tabular-nums">
                  {r.tokens.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
