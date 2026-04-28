import { useParams, Link } from "react-router-dom";
import { useAgent } from "@/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { ArrowLeft, Settings, MessageSquare } from "lucide-react";

export default function AdminAgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { agent, isLoading } = useAgent(id);

  if (isLoading) return <LoadingSpinner size="lg" className="mt-24" />;
  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <p className="text-lg text-muted-foreground">Agent不存在</p>
        <Link to="/admin/agents" className="mt-4">
          <Button variant="outline"><ArrowLeft className="mr-2 h-4 w-4" />返回列表</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/admin/agents">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold">{agent.name}</h1>
          <p className="text-muted-foreground">{agent.agent_type}</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Settings className="h-4 w-4" />基础配置
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <InfoRow label="类型" value={agent.agent_type} />
            <InfoRow label="状态" value={agent.is_active ? "启用" : "禁用"} />
            <InfoRow label="模型" value={agent.model_name} />
            <InfoRow label="温度" value={String(agent.temperature)} />
            <InfoRow label="创建时间" value={new Date(agent.created_at).toLocaleString("zh-CN")} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MessageSquare className="h-4 w-4" />系统提示词
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap rounded-md bg-muted p-4 text-sm">
              {agent.system_prompt || "未设置系统提示词"}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
