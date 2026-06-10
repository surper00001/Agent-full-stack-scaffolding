import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Search,
  Zap,
  Shield,
  Play,
  Trash2,
  Archive,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Container,
  LayoutList,
  Columns3,
} from "lucide-react";
import { useSkillStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { getStatusColor } from "@/components/harness";
import { STATUS_LABELS } from "@/types/skill";
import { cn } from "@/lib/utils";
import { useConfirm } from "@/hooks/use-confirm";
import type { Skill } from "@/types/skill";

const CATEGORY_ICONS: Record<string, string> = {
  file: "📄",
  shell: "💻",
  network: "🌐",
  knowledge: "📚",
  custom: "🔧",
  meta: "🔄",
};

const SECURITY_ICONS: Record<string, typeof Shield> = {
  low: ShieldCheck,
  medium: Shield,
  high: ShieldAlert,
  critical: ShieldOff,
};

const SECURITY_COLORS: Record<string, string> = {
  low: "text-green-600 bg-green-50",
  medium: "text-yellow-600 bg-yellow-50",
  high: "text-orange-600 bg-orange-50",
  critical: "text-red-600 bg-red-50",
};

// Pipeline 看板列定义
const PIPELINE_COLUMNS = [
  { status: "draft", label: "草稿", color: "border-l-gray-400" },
  { status: "testing", label: "测试中", color: "border-l-blue-400" },
  { status: "pending_review", label: "待审核", color: "border-l-yellow-400" },
  { status: "approved", label: "已审核", color: "border-l-green-400" },
  { status: "published", label: "已发布", color: "border-l-indigo-400" },
  { status: "active", label: "已激活", color: "border-l-emerald-400" },
  { status: "deprecated", label: "已弃用", color: "border-l-orange-400" },
  { status: "archived", label: "已归档", color: "border-l-gray-400" },
];

type ViewMode = "table" | "pipeline";

export default function SkillsPage() {
  const navigate = useNavigate();
  const {
    skills,
    isLoading,
    total,
    fetchSkills,
    deleteSkill,
    publishSkill,
    deprecateSkill,
  } = useSkillStore();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [viewMode, setViewMode] = useState<ViewMode>("pipeline");
  const pageSize = 20;

  useEffect(() => {
    fetchSkills(page, pageSize, statusFilter || undefined);
  }, [page, statusFilter, fetchSkills]);

  const filtered = useMemo(
    () =>
      skills.filter(
        (s) =>
          s.name.toLowerCase().includes(search.toLowerCase()) ||
          s.display_name.toLowerCase().includes(search.toLowerCase()) ||
          s.description.toLowerCase().includes(search.toLowerCase())
      ),
    [skills, search]
  );

  // 按状态分组 (给 pipeline 视图)
  const groupedByStatus = useMemo(() => {
    const groups: Record<string, Skill[]> = {};
    for (const col of PIPELINE_COLUMNS) {
      groups[col.status] = [];
    }
    for (const skill of filtered) {
      if (groups[skill.status]) {
        groups[skill.status].push(skill);
      }
    }
    return groups;
  }, [filtered]);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Zap className="w-6 h-6 text-emerald-600" />
            Skill 管理
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Harness 工程 · AI 能力单元全生命周期管理
          </p>
        </div>
        <Button onClick={() => navigate("/admin/skills/new")}>
          <Plus className="w-4 h-4 mr-2" />
          新建 Skill
        </Button>
      </div>

      {/* Filters + View Toggle */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-3">
          <div className="relative w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="搜索 Skill..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="border rounded-md px-3 py-2 text-sm bg-background"
          >
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="testing">测试中</option>
            <option value="pending_review">待审核</option>
            <option value="approved">已审核</option>
            <option value="published">已发布</option>
            <option value="active">已激活</option>
            <option value="deprecated">已弃用</option>
            <option value="archived">已归档</option>
          </select>
        </div>

        {/* 视图切换 */}
        <div className="flex items-center border rounded-md overflow-hidden">
          <button
            onClick={() => setViewMode("table")}
            className={cn(
              "px-3 py-1.5 text-sm flex items-center gap-1 transition-colors",
              viewMode === "table"
                ? "bg-emerald-50 text-emerald-700 font-medium"
                : "hover:bg-muted"
            )}
          >
            <LayoutList className="w-4 h-4" />
            列表
          </button>
          <button
            onClick={() => setViewMode("pipeline")}
            className={cn(
              "px-3 py-1.5 text-sm flex items-center gap-1 transition-colors",
              viewMode === "pipeline"
                ? "bg-emerald-50 text-emerald-700 font-medium"
                : "hover:bg-muted"
            )}
          >
            <Columns3 className="w-4 h-4" />
            管道
          </button>
        </div>
      </div>

      {/* ── 管道/看板视图 ── */}
      {viewMode === "pipeline" && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-8 gap-3">
          {PIPELINE_COLUMNS.map((col) => {
            const items = groupedByStatus[col.status] ?? [];
            return (
              <div
                key={col.status}
                className={cn(
                  "border-t-2 rounded-lg bg-muted/20 min-h-[120px]",
                  col.color
                )}
              >
                <div className="px-3 py-2 border-b bg-background/50 rounded-t-lg flex items-center justify-between">
                  <span className="text-xs font-semibold">{col.label}</span>
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full">
                    {items.length}
                  </span>
                </div>
                <div className="p-2 space-y-1.5 max-h-[400px] overflow-y-auto">
                  {items.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground text-center py-4">
                      暂无
                    </p>
                  ) : (
                    items.map((skill) => (
                      <PipelineCard
                        key={skill.id}
                        skill={skill}
                        onClick={() => navigate(`/admin/skills/${skill.id}`)}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── 表格视图 ── */}
      {viewMode === "table" && (
        <>
          {isLoading ? (
            <LoadingSpinner />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Zap className="w-12 h-12" />}
              title="还没有 Skill"
              description='在对话中说 "帮我创建一个 XXX Skill"，AI 会自动生成。'
            />
          ) : (
            <Card>
              <CardContent className="p-0">
                <table className="w-full">
                  <thead>
                    <tr className="border-b text-sm text-muted-foreground">
                      <th className="text-left p-4 font-medium">名称</th>
                      <th className="text-left p-4 font-medium">分类</th>
                      <th className="text-left p-4 font-medium">安全</th>
                      <th className="text-left p-4 font-medium">沙箱</th>
                      <th className="text-left p-4 font-medium">状态</th>
                      <th className="text-left p-4 font-medium">调用</th>
                      <th className="text-right p-4 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((skill) => (
                      <SkillRow
                        key={skill.id}
                        skill={skill}
                        onView={(id) => navigate(`/admin/skills/${id}`)}
                        onPublish={(id) => publishSkill(id)}
                        onDeprecate={(id) => deprecateSkill(id)}
                        onDelete={(id) =>
                          deleteSkill(id).then(() =>
                            fetchSkills(page, pageSize, statusFilter || undefined)
                          )
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Pagination */}
      {viewMode === "table" && total > pageSize && (
        <div className="flex justify-center gap-2">
          <Button
            variant="outline"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </Button>
          <span className="px-4 py-2 text-sm">
            {page} / {Math.ceil(total / pageSize)}
          </span>
          <Button
            variant="outline"
            disabled={page * pageSize >= total}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Pipeline 看板卡片 ──

function PipelineCard({
  skill,
  onClick,
}: {
  skill: Skill;
  onClick: () => void;
}) {
  const SecIcon = SECURITY_ICONS[skill.security_level] ?? Shield;

  return (
    <div
      onClick={onClick}
      className="bg-background border rounded-md p-2 cursor-pointer hover:shadow-sm hover:border-emerald-200 transition-all text-xs"
    >
      <div className="font-medium flex items-center gap-1 truncate">
        {CATEGORY_ICONS[skill.category] ?? "🔧"}
        <span className="truncate">{skill.display_name}</span>
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <div className="flex items-center gap-1">
          <SecIcon
            className={cn("w-3 h-3", SECURITY_COLORS[skill.security_level]?.split(" ")[0])}
          />
          <span className="text-[10px] text-muted-foreground">{skill.security_level}</span>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
          {skill.requires_sandbox && <Container className="w-3 h-3" />}
          <span>{skill.usage_count}</span>
        </div>
      </div>
    </div>
  );
}

// ── 表格行 ──

function SkillRow({
  skill,
  onView,
  onPublish,
  onDeprecate,
  onDelete,
}: {
  skill: Skill;
  onView: (id: string) => void;
  onPublish: (id: string) => void;
  onDeprecate: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [acting, setActing] = useState(false);
  const confirm = useConfirm();
  const SecIcon = SECURITY_ICONS[skill.security_level] ?? Shield;

  return (
    <tr className="border-b hover:bg-muted/50 transition-colors cursor-pointer">
      {/* 名称 */}
      <td className="p-4" onClick={() => onView(skill.id)}>
        <div className="font-medium flex items-center gap-2">
          {CATEGORY_ICONS[skill.category] || "🔧"} {skill.display_name}
        </div>
        <div className="text-xs text-muted-foreground font-mono mt-0.5">
          {skill.name} v{skill.version}
        </div>
      </td>
      {/* 分类 */}
      <td className="p-4 text-sm capitalize" onClick={() => onView(skill.id)}>
        {skill.category}
      </td>
      {/* 安全级别 */}
      <td className="p-4" onClick={() => onView(skill.id)}>
        <span
          className={cn(
            "inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full",
            SECURITY_COLORS[skill.security_level] ?? "bg-gray-100 text-gray-500"
          )}
        >
          <SecIcon className="w-3 h-3" />
          {skill.security_level}
        </span>
      </td>
      {/* 沙箱 */}
      <td className="p-4" onClick={() => onView(skill.id)}>
        {skill.requires_sandbox ? (
          <span className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full">
            <Container className="w-3 h-3" />
            沙箱
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </td>
      {/* 状态 */}
      <td className="p-4" onClick={() => onView(skill.id)}>
        <span
          className={cn(
            "text-xs px-2 py-0.5 rounded-full font-medium",
            getStatusColor(skill.status)
          )}
        >
          {STATUS_LABELS[skill.status] || skill.status}
        </span>
      </td>
      {/* 调用次数 */}
      <td className="p-4 text-sm" onClick={() => onView(skill.id)}>
        {skill.usage_count.toLocaleString()}
      </td>
      {/* 操作 */}
      <td className="p-4 text-right">
        <div className="flex items-center justify-end gap-1">
          {(skill.status === "draft" || skill.status === "testing") && (
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                setActing(true);
                onPublish(skill.id).finally(() => setActing(false));
              }}
              disabled={acting}
              title="发布激活"
            >
              <Play className="w-3 h-3" />
            </Button>
          )}
          {skill.status === "active" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                setActing(true);
                onDeprecate(skill.id).finally(() => setActing(false));
              }}
              disabled={acting}
              title="弃用"
            >
              <Archive className="w-3 h-3" />
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={async (e) => {
              e.stopPropagation();
              if (await confirm({ description: `确认删除 Skill "${skill.display_name}"？`, variant: "destructive" })) {
                onDelete(skill.id);
              }
            }}
            title="删除"
          >
            <Trash2 className="w-3 h-3 text-red-500" />
          </Button>
        </div>
      </td>
    </tr>
  );
}
