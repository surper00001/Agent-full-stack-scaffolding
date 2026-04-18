import { useState } from "react";
import { Link } from "react-router-dom";
import { useAgents } from "@/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { useDebounce } from "@/hooks";
import { Plus, Search } from "lucide-react";
import type { AgentType, CreateAgentRequest } from "@/types";

const AGENT_TYPES: { value: AgentType; label: string }[] = [
  { value: "chat", label: "对话型" },
  { value: "tool_use", label: "工具使用" },
  { value: "rag", label: "RAG检索" },
  { value: "multi_agent", label: "多Agent协作" },
];

/**
 * Agent管理列表页
 * 支持搜索、创建、删除Agent
 */
export default function AgentsPage() {
  const { agents, isLoading, createAgent, deleteAgent } = useAgents();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 300);

  // 新建Agent表单
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    type: "chat" as AgentType,
  });
  const [submitting, setSubmitting] = useState(false);

  // 搜索过滤
  const filteredAgents = agents.filter(
    (a) =>
      a.name.toLowerCase().includes(debouncedSearch.toLowerCase()) ||
      a.description?.toLowerCase().includes(debouncedSearch.toLowerCase()),
  );

  const handleCreate = async () => {
    setSubmitting(true);
    try {
      await createAgent(form as CreateAgentRequest);
      setDialogOpen(false);
      setForm({ name: "", description: "", type: "chat" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* 页面头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Agent 管理</h1>
          <p className="text-muted-foreground">创建和管理你的AI Agent</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              创建Agent
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>创建新Agent</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">名称</label>
                <Input
                  placeholder="Agent名称"
                  value={form.name}
                  onChange={(e) =>
                    setForm({ ...form, name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">描述</label>
                <Input
                  placeholder="Agent功能描述"
                  value={form.description}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">类型</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={form.type}
                  onChange={(e) =>
                    setForm({ ...form, type: e.target.value as AgentType })
                  }
                >
                  {AGENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                className="w-full"
                onClick={handleCreate}
                disabled={!form.name || submitting}
              >
                {submitting ? "创建中..." : "确认创建"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* 搜索栏 */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="搜索Agent..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Agent列表 */}
      {isLoading ? (
        <LoadingSpinner size="lg" className="mt-12" />
      ) : filteredAgents.length === 0 ? (
        <EmptyState
          title="暂无Agent"
          description={search ? "没有匹配的Agent" : "点击右上角创建第一个Agent"}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredAgents.map((agent) => (
            <Link key={agent.id} to={`/agents/${agent.id}`}>
              <Card className="transition-shadow hover:shadow-md">
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-lg">{agent.name}</CardTitle>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        agent.status === "active"
                          ? "bg-green-100 text-green-700"
                          : agent.status === "error"
                            ? "bg-red-100 text-red-700"
                            : "bg-gray-100 text-gray-700"
                      }`}
                    >
                      {agent.status}
                    </span>
                  </div>
                  <CardDescription>
                    {agent.description || "暂无描述"}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{AGENT_TYPES.find((t) => t.value === agent.type)?.label}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        if (confirm("确定删除该Agent？")) {
                          deleteAgent(agent.id);
                        }
                      }}
                    >
                      删除
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
