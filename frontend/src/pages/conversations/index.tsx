import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useConversations } from "@/hooks";
import { useConfirm } from "@/hooks/use-confirm";
import {
  Card,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { EmptyState } from "@/components/common/empty-state";
import { MessageSquare, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * 对话列表页
 * 展示所有历史对话，支持删除
 */
export default function ConversationsPage() {
  const confirm = useConfirm();
  const {
    conversations,
    isLoading,
    fetchConversations,
    deleteConversation,
  } = useConversations();

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">对话记录</h1>
        <p className="text-muted-foreground">查看和管理Agent对话历史</p>
      </div>

      {isLoading ? (
        <LoadingSpinner size="lg" className="mt-12" />
      ) : conversations.length === 0 ? (
        <EmptyState
          title="暂无对话记录"
          description="与Agent对话后，记录将在此显示"
          icon={<MessageSquare className="mb-4 h-12 w-12 text-muted-foreground" />}
        />
      ) : (
        <div className="space-y-3">
          {conversations.map((conv) => (
            <Link key={conv.id} to={`/conversations/${conv.id}`}>
              <Card className="transition-shadow hover:shadow-md">
                <CardHeader className="flex flex-row items-center justify-between">
                  <div>
                    <CardTitle className="text-base">
                      {conv.title || "未命名对话"}
                    </CardTitle>
                    <p className="text-sm text-muted-foreground">
                      {conv.messages?.length ?? 0} 条消息 ·{" "}
                      {new Date(conv.created_at).toLocaleString("zh-CN")}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive"
                    onClick={async (e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      if (await confirm({ description: "确定删除该对话？", variant: "destructive" })) {
                        deleteConversation(conv.id);
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </CardHeader>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
