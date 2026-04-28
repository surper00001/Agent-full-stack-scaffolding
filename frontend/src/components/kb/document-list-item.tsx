import { Link } from "react-router-dom";
import { Eye, Download, Trash2, RefreshCw, File } from "lucide-react";
import * as kbApi from "@/api/knowledge-base";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { KBDocumentListItem } from "@/types";
import { DOC_STATUS_LABELS, FILE_TYPE_ICONS, formatFileSize } from "./constants";

interface DocumentListItemProps {
  doc: KBDocumentListItem;
  kbId: string;
  onDelete: (docId: string, filename: string) => Promise<void>;
  onReprocess: (docId: string, filename: string) => Promise<void>;
}

export function DocumentListItem({ doc, kbId, onDelete, onReprocess }: DocumentListItemProps) {
  const Icon = FILE_TYPE_ICONS[doc.file_type] || File;
  const isFailed = doc.status === "error" || Boolean(doc.error_message);
  const displayStatus = isFailed ? "error" : doc.status;

  const statusClass =
    displayStatus === "ready"
      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
      : displayStatus === "processing"
        ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
        : displayStatus === "error"
          ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
          : "bg-gray-100 text-gray-600";

  return (
    <Card className={`group ${isFailed ? "border-red-200 dark:border-red-900/50" : ""}`}>
      <CardContent className="flex items-center gap-3 py-3">
        <Icon className="h-8 w-8 text-muted-foreground shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{doc.filename}</p>
          <p className="text-xs text-muted-foreground">
            {formatFileSize(doc.file_size)}
            {doc.page_count > 0 ? ` · ${doc.page_count} 页` : ""}
            {` · ${doc.chunk_count} 分块`}
            <span
              className={`ml-2 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${statusClass}`}
            >
              {DOC_STATUS_LABELS[displayStatus] || displayStatus}
            </span>
          </p>
          {doc.error_message && (
            <p className="text-xs text-red-600 dark:text-red-400 mt-1 line-clamp-2">{doc.error_message}</p>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isFailed && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-amber-700 border-amber-300 hover:bg-amber-50 dark:text-amber-400"
              onClick={() => onReprocess(doc.id, doc.filename)}
            >
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
              重试
            </Button>
          )}
          <div className="flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
            <Link to={`/kb/${kbId}/documents/${doc.id}`}>
              <Button variant="ghost" size="icon" className="h-8 w-8" title="查看文档">
                <Eye className="h-4 w-4" />
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="下载源文件"
              onClick={() => kbApi.downloadDocument(kbId, doc.id, doc.filename)}
            >
              <Download className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-destructive hover:text-destructive"
              title="删除"
              onClick={() => onDelete(doc.id, doc.filename)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
