import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useKBStore } from "@/stores";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { Plus, Search, Library, FileText, HardDrive, Trash2 } from "lucide-react";

export default function KnowledgeBasesPage() {
  const { kbList, kbLoading, fetchKBList, createKB, deleteKB } = useKBStore();
  const [search, setSearch] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchKBList(1, 50);
  }, [fetchKBList]);

  const filtered = kbList.filter(
    (k) =>
      k.name.toLowerCase().includes(search.toLowerCase()) ||
      (k.description || "").toLowerCase().includes(search.toLowerCase()),
  );

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setSubmitting(true);
    try {
      await createKB(newName.trim(), newDesc.trim() || undefined);
      setDialogOpen(false);
      setNewName("");
      setNewDesc("");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string, name: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`确定删除知识库「${name}」？所有文档和索引将被清除。`)) return;
    await deleteKB(id);
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">知识库</h1>
          <p className="text-muted-foreground">管理你的个人知识文档，支持 PDF、Word、图片等格式</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button><Plus className="mr-2 h-4 w-4" />新建知识库</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>新建知识库</DialogTitle></DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">名称</label>
                <Input
                  placeholder="例如：项目文档、学习笔记"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">描述（可选）</label>
                <Input
                  placeholder="简要描述知识库的内容"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                />
              </div>
              <Button className="w-full" onClick={handleCreate} disabled={!newName.trim() || submitting}>
                {submitting ? "创建中..." : "确认创建"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="搜索知识库..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {kbLoading ? (
        <LoadingSpinner size="lg" className="mt-12" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="暂无知识库"
          description={search ? "没有匹配的知识库" : "点击右上角「新建知识库」上传你的第一个文档"}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((kb) => (
            <Link key={kb.id} to={`/kb/${kb.id}`}>
              <Card className="group transition-shadow hover:shadow-md cursor-pointer">
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Library className="h-5 w-5 text-primary" />
                      <CardTitle className="text-lg">{kb.name}</CardTitle>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 opacity-0 group-hover:opacity-100 text-destructive hover:text-destructive"
                      onClick={(e) => handleDelete(e, kb.id, kb.name)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  {kb.description && (
                    <CardDescription className="line-clamp-2">{kb.description}</CardDescription>
                  )}
                </CardHeader>
                <CardContent>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <FileText className="h-3.5 w-3.5" />
                      {kb.document_count} 个文档
                    </span>
                    <span className="flex items-center gap-1">
                      <HardDrive className="h-3.5 w-3.5" />
                      {formatSize(kb.total_size_bytes)}
                    </span>
                    <span className="ml-auto rounded-full bg-primary/10 px-2 py-0.5 text-primary text-[10px]">
                      {kb.total_chunks} 分块
                    </span>
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
