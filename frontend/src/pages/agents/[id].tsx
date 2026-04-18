import { useParams, Link } from "react-router-dom";
import { useAgent } from "@/hooks";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { ArrowLeft, Settings, MessageSquare } from "lucide-react";

/**
 * Agent详情页
 * 展示单个Agent的完整信息和配置
 */
export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { agent, isLoading } = useAgent(id);

  if (isLoading) return <LoadingSpinner size="lg" className="mt-24" />;
  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <p className="text-lg text-muted-foreground">Agent不存在</p>
        <Link to="/agents" className="mt-4">
          <Button variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            返回列表
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 面包屑导航 */}
      <div className="flex items-center gap-4">
        <Link to="/agents">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold">{agent.name}</h1>
          <p className="text-muted-foreground">{agent.description}</p>
        </div>
      </div>

      {/* 基础信息 */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Settings className="h-4 w-4" />
              基础配置
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <InfoRow label="类型" value={agent.type} />
            <InfoRow label="状态" value={agent.status} />
            <InfoRow label="模型" value={agent.config.model} />
            <InfoRow
              label="温度"
              value={String(agent.config.temperature)}
            />
            <InfoRow
              label="最大Token"
              value={String(agent.config.max_tokens)}
            />
            <InfoRow
              label="创建时间"
              value={new Date(agent.created_at).toLocaleString("zh-CN")}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MessageSquare className="h-4 w-4" />
              系统提示词
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap rounded-md bg-muted p-4 text-sm">
              {agent.config.system_prompt || "未设置系统提示词"}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/** 信息行辅助组件 */
function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
