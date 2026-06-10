import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { useUserAdminStore } from "@/stores";
import { useConfirm } from "@/hooks/use-confirm";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { Search, Users, Shield, UserX, Trash2, ChevronLeft, ChevronRight } from "lucide-react";
import { useDebounce } from "@/hooks";

const PAGE_SIZE = 20;

export default function AdminUsersPage() {
  const confirm = useConfirm();
  const { users, total, loading, fetchUsers, deleteUser, toggleUserActive } = useUserAdminStore();
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebounce(searchInput, 300);

  useEffect(() => {
    fetchUsers(page, PAGE_SIZE, debouncedSearch || undefined);
  }, [page, debouncedSearch, fetchUsers]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleDelete = useCallback(
    async (userId: string, username: string) => {
      if (!await confirm({ description: `确定删除用户「${username}」？此操作不可恢复。`, variant: "destructive" })) return;
      await deleteUser(userId);
    },
    [deleteUser, confirm],
  );

  const handleToggleActive = useCallback(
    async (userId: string, username: string, currentActive: boolean) => {
      const action = currentActive ? "禁用" : "启用";
      if (!await confirm({ description: `确定${action}用户「${username}」？` })) return;
      await toggleUserActive(userId);
    },
    [toggleUserActive, confirm],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">用户管理</h1>
        <p className="text-muted-foreground">管理系统中的所有注册用户</p>
      </div>

      {/* 搜索栏 */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索用户名、邮箱或手机号..."
            value={searchInput}
            onChange={(e) => {
              setSearchInput(e.target.value);
              setPage(1);
            }}
            className="pl-9"
          />
        </div>
        <span className="text-sm text-muted-foreground">共 {total} 个用户</span>
      </div>

      {/* 用户列表 */}
      {loading ? (
        <LoadingSpinner size="lg" className="mt-12" />
      ) : users.length === 0 ? (
        <EmptyState
          title="暂无用户"
          description={searchInput ? "未找到匹配的用户" : "系统尚无注册用户"}
          icon={<Users className="mb-4 h-12 w-12 text-muted-foreground" />}
        />
      ) : (
        <div className="space-y-3">
          {users.map((user) => (
            <Link key={user.id} to={`/admin/users/${user.id}`}>
              <Card className="transition-shadow hover:shadow-md cursor-pointer">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                        <span className="text-sm font-bold text-primary">
                          {user.username.slice(0, 2).toUpperCase()}
                        </span>
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <CardTitle className="text-base">{user.username}</CardTitle>
                          {user.role === "admin" && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                              <Shield className="h-3 w-3" />
                              管理员
                            </span>
                          )}
                          {!user.is_active && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">
                              <UserX className="h-3 w-3" />
                              已禁用
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {user.email || "无邮箱"} · {user.conversation_count} 个对话 · {user.total_tokens.toLocaleString()} tokens
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2" onClick={(e) => e.preventDefault()}>
                      {/* 启用/禁用 */}
                      {user.role !== "admin" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggleActive(user.id, user.username, user.is_active);
                          }}
                        >
                          {user.is_active ? "禁用" : "启用"}
                        </Button>
                      )}
                      {/* 删除 */}
                      {user.role !== "admin" && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-destructive hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(user.id, user.username);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                </CardHeader>
              </Card>
            </Link>
          ))}

          {/* 分页 */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-4 w-4" />
                上一页
              </Button>
              <span className="text-sm text-muted-foreground">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
