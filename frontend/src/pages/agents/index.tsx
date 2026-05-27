import { useState } from "react";
import { Link } from "react-router-dom";
import { useAgents } from "@/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { useDebounce } from "@/hooks";
import { Plus, Search } from "lucide-react";
import type { CreateAgentRequest } from "@/types";

const AGENT_TYPES = [
  { value: "creative", label: "创意导演·五人顾问团" },
  { value: "mindmap", label: "思维导图助手" },
  { value: "default", label: "通用助手" },
];

export default function AgentsPage() {
  const { agents, isLoading, createAgent, deleteAgent } = useAgents();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 300);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", agent_type: "creative", system_prompt: "" });
  const [submitting, setSubmitting] = useState(false);

  const filteredAgents = agents.filter((a) =>
    a.name.toLowerCase().includes(debouncedSearch.toLowerCase()),
  );

  const handleCreate = async () => {
    setSubmitting(true);
    try {
      await createAgent(form as CreateAgentRequest);
      setDialogOpen(false);
      setForm({ name: "", agent_type: "creative", system_prompt: "" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Agent 管理</h1>
          <p className="text-muted-foreground">创建和管理你的AI Agent</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button><Plus className="mr-2 h-4 w-4" />创建Agent</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>创建新Agent</DialogTitle></DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">名称</label>
                <Input placeholder="Agent名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">类型</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={form.agent_type}
                  onChange={(e) => setForm({ ...form, agent_type: e.target.value })}
                >
                  {AGENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">系统提示词</label>
                <Input placeholder="系统提示词（可选）" value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
              </div>
              <Button className="w-full" onClick={handleCreate} disabled={!form.name || submitting}>
                {submitting ? "创建中..." : "确认创建"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="搜索Agent..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>

      {isLoading ? (
        <LoadingSpinner size="lg" className="mt-12" />
      ) : filteredAgents.length === 0 ? (
        <EmptyState title="暂无Agent" description={search ? "没有匹配的Agent" : "点击右上角创建第一个Agent"} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredAgents.map((agent) => (
            <Link key={agent.id} to={`/agents/${agent.id}`}>
              <Card className="transition-shadow hover:shadow-md">
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-lg">{agent.name}</CardTitle>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${agent.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                      {agent.is_active ? "启用" : "禁用"}
                    </span>
                  </div>
                  <CardDescription>{AGENT_TYPES.find((t) => t.value === agent.agent_type)?.label || agent.agent_type}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{agent.model_name}</span>
                    <Button
                      variant="ghost" size="sm" className="text-destructive hover:text-destructive"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (confirm("确定删除该Agent？")) deleteAgent(agent.id); }}
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
