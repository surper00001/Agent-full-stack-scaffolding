import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useUserAdminStore } from "@/stores";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import {
  ArrowLeft,
  MessageSquare,
  Trash2,
  Shield,
  UserX,
  UserCheck,
  BarChart3,
  Zap,
  Calendar,
  Edit3,
  Save,
  X,
} from "lucide-react";

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    currentUser,
    detailLoading,
    tokenTrend,
    tokenUsage,
    trendLoading,
    userConversations,
    convLoading,
    fetchUserDetail,
    fetchUserConversations,
    fetchUserTokenUsage,
    fetchUserTokenTrend,
    deleteUserConversations,
    setTokenQuota,
    updateUserRole,
    toggleUserActive,
    reset,
  } = useUserAdminStore();

  const [trendDays, setTrendDays] = useState(7);
  const [editingQuota, setEditingQuota] = useState(false);
  const [quotaInput, setQuotaInput] = useState("");

  useEffect(() => {
    if (!id) return;
    fetchUserDetail(id);
    fetchUserConversations(id);
    fetchUserTokenUsage(id);
    fetchUserTokenTrend(id, trendDays);
    return () => reset();
  }, [id, trendDays, fetchUserDetail, fetchUserConversations, fetchUserTokenUsage, fetchUserTokenTrend, reset]);

  const handleDeleteConversations = useCallback(async () => {
    if (!id || !currentUser) return;
    if (!confirm(`确定清空用户「${currentUser.username}」的所有对话记录？此操作不可恢复。`)) return;
    await deleteUserConversations(id);
  }, [id, currentUser, deleteUserConversations]);

  const handleSaveQuota = useCallback(async () => {
    if (!id) return;
    const quota = parseInt(quotaInput, 10);
    if (isNaN(quota) || quota < 0) return;
    await setTokenQuota(id, quota);
    setEditingQuota(false);
  }, [id, quotaInput, setTokenQuota]);

  const handleToggleActive = useCallback(async () => {
    if (!id || !currentUser) return;
    const action = currentUser.is_active ? "禁用" : "启用";
    if (!confirm(`确定${action}用户「${currentUser.username}」？`)) return;
    await toggleUserActive(id);
  }, [id, currentUser, toggleUserActive]);

  const handleRoleChange = useCallback(async () => {
    if (!id || !currentUser) return;
    const newRole = currentUser.role === "admin" ? "user" : "admin";
    const action = newRole === "admin" ? "提升为管理员" : "降级为普通用户";
    if (!confirm(`确定将「${currentUser.username}」${action}？`)) return;
    await updateUserRole(id, newRole);
  }, [id, currentUser, updateUserRole]);

  if (!id) return null;
  if (detailLoading || !currentUser) {
    return <LoadingSpinner size="lg" className="mt-24" />;
  }

  const maxTrendTokens = Math.max(1, ...(tokenTrend || [{ tokens: 0 }]).map((d) => d.tokens));

  return (
    <div className="space-y-6">
      {/* 返回按钮 */}
      <button
        onClick={() => navigate("/admin/users")}
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        返回用户列表
      </button>

      {/* 用户基本信息 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
              <span className="text-lg font-bold text-primary">
                {currentUser.username.slice(0, 2).toUpperCase()}
              </span>
            </div>
            <div>
              <div className="flex items-center gap-3">
                <CardTitle className="text-xl">{currentUser.username}</CardTitle>
                {currentUser.role === "admin" ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    <Shield className="h-3.5 w-3.5" />
                    管理员
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                    普通用户
                  </span>
                )}
                {currentUser.is_active ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                    <UserCheck className="h-3.5 w-3.5" />
                    正常
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-3 py-1 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">
                    <UserX className="h-3.5 w-3.5" />
                    已禁用
                  </span>
                )}
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                {currentUser.email || "无邮箱"}
                {currentUser.phone && ` · ${currentUser.phone}`}
                {" · "}注册于 {new Date(currentUser.created_at).toLocaleDateString("zh-CN")}
              </p>
            </div>
          </div>

          {/* 操作按钮 */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleRoleChange}>
              <Shield className="h-4 w-4 mr-1" />
              {currentUser.role === "admin" ? "降级" : "提升管理员"}
            </Button>
            <Button variant="outline" size="sm" onClick={handleToggleActive}>
              {currentUser.is_active ? "禁用" : "启用"}
            </Button>
          </div>
        </CardHeader>
      </Card>

      {/* 统计卡片 */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">对话总数</CardTitle>
            <MessageSquare className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentUser.conversation_count}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Token 消耗</CardTitle>
            <Zap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentUser.total_tokens.toLocaleString()}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Token 配额</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {editingQuota ? (
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  value={quotaInput}
                  onChange={(e) => setQuotaInput(e.target.value)}
                  className="h-8 w-28 text-sm"
                  placeholder="0=无限制"
                />
                <Button size="icon" variant="ghost" className="h-7 w-7" onClick={handleSaveQuota}>
                  <Save className="h-3.5 w-3.5" />
                </Button>
                <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setEditingQuota(false)}>
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <div className="text-2xl font-bold">
                  {currentUser.token_quota != null ? currentUser.token_quota.toLocaleString() : "无限制"}
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={() => {
                    setQuotaInput(currentUser.token_quota?.toString() || "0");
                    setEditingQuota(true);
                  }}
                >
                  <Edit3 className="h-3.5 w-3.5 text-muted-foreground" />
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">注册时间</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-lg font-bold">
              {new Date(currentUser.created_at).toLocaleDateString("zh-CN")}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Token 使用趋势图 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg">Token 使用趋势</CardTitle>
          <div className="flex items-center gap-2">
            {[7, 14, 30].map((d) => (
              <Button
                key={d}
                variant={trendDays === d ? "default" : "outline"}
                size="sm"
                onClick={() => setTrendDays(d)}
              >
                {d}天
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {trendLoading ? (
            <LoadingSpinner size="sm" />
          ) : tokenTrend && tokenTrend.length > 0 ? (
            <div className="space-y-2">
              <div className="flex items-end gap-1 h-40">
                {tokenTrend.map((item) => {
                  const height = maxTrendTokens > 0 ? (item.tokens / maxTrendTokens) * 100 : 0;
                  return (
                    <div
                      key={item.date}
                      className="flex-1 flex flex-col items-center gap-1"
                      title={`${item.date}: ${item.tokens.toLocaleString()} tokens`}
                    >
                      <span className="text-[10px] text-muted-foreground">
                        {item.tokens > 0 ? item.tokens.toLocaleString() : ""}
                      </span>
                      <div className="flex flex-col justify-end flex-1 w-full">
                        <div
                          className="w-full rounded-t bg-primary/60 hover:bg-primary transition-colors min-h-[2px]"
                          style={{ height: `${Math.max(height, 1)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex gap-1">
                {tokenTrend.map((item) => (
                  <div key={item.date} className="flex-1 text-center">
                    <span className="text-[10px] text-muted-foreground">
                      {item.date.slice(5)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-8">
              暂无 Token 使用数据
            </p>
          )}
        </CardContent>
      </Card>

      {/* 按对话的 Token 明细 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Token 消耗明细（按对话）</CardTitle>
        </CardHeader>
        <CardContent>
          {tokenUsage && tokenUsage.by_conversation.length > 0 ? (
            <div className="space-y-2 max-h-64 overflow-y-auto app-scrollbar">
              {tokenUsage.by_conversation.map((item) => (
                <div
                  key={item.conversation_id}
                  className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                >
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-medium">{item.conversation_title}</p>
                    <p className="text-xs text-muted-foreground">
                      {item.message_count} 条消息 · {new Date(item.created_at).toLocaleDateString("zh-CN")}
                    </p>
                  </div>
                  <span className="ml-3 shrink-0 font-mono text-sm font-medium">
                    {item.tokens.toLocaleString()} tokens
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-8">
              暂无 Token 消耗记录
            </p>
          )}
        </CardContent>
      </Card>

      {/* 用户对话列表 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg">对话记录</CardTitle>
          {currentUser.conversation_count > 0 && (
            <Button variant="outline" size="sm" onClick={handleDeleteConversations} className="text-destructive hover:text-destructive">
              <Trash2 className="h-4 w-4 mr-1" />
              清空所有对话
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {convLoading ? (
            <LoadingSpinner size="sm" />
          ) : userConversations.length > 0 ? (
            <div className="space-y-2 max-h-80 overflow-y-auto app-scrollbar">
              {userConversations.map((conv) => (
                <div
                  key={conv.id}
                  className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                >
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-medium">{conv.title || "未命名对话"}</p>
                    <p className="text-xs text-muted-foreground">
                      {conv.agent_type} · {conv.message_count} 条消息 · {conv.total_tokens.toLocaleString()} tokens · {new Date(conv.created_at).toLocaleDateString("zh-CN")}
                    </p>
                  </div>
                  <span className={`ml-3 shrink-0 rounded-full px-2 py-0.5 text-xs ${conv.status === "active" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                    {conv.status === "active" ? "进行中" : "已归档"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-8">
              该用户暂无对话记录
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
