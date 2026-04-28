import { FileText, Image, type LucideIcon } from "lucide-react";

export const FILE_TYPE_ICONS: Record<string, LucideIcon> = {
  pdf: FileText,
  docx: FileText,
  doc: FileText,
  txt: FileText,
  md: FileText,
  png: Image,
  jpg: Image,
  jpeg: Image,
  bmp: Image,
  tiff: Image,
  tif: Image,
};

export const DOC_STATUS_LABELS: Record<string, string> = {
  uploading: "上传中",
  processing: "处理中",
  ready: "就绪",
  error: "失败",
};

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
