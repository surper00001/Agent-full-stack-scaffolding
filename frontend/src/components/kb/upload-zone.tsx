import { useState } from "react";
import { Upload, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface UploadZoneProps {
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function UploadZone({ uploading, fileInputRef, onUpload }: UploadZoneProps) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = e.dataTransfer.files;
    if (files.length === 0) return;
    const input = fileInputRef.current;
    if (!input) return;
    const dt = new DataTransfer();
    Array.from(files).forEach((f) => dt.items.add(f));
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
        dragOver ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/50"
      }`}
    >
      <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
      <p className="text-sm text-muted-foreground mb-2">拖拽文件到此处，或点击下方按钮选择文件</p>
      <p className="text-xs text-muted-foreground/60 mb-3">
        支持 PDF、Word (.docx)、TXT、Markdown、PNG、JPG 等格式，单文件最大 50MB
      </p>
      <input
        ref={fileInputRef as React.Ref<HTMLInputElement>}
        type="file"
        multiple
        accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.png,.jpg,.jpeg,.bmp,.tiff,.tif"
        onChange={onUpload}
        className="hidden"
      />
      <Button variant="outline" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
        {uploading ? (
          <>
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            上传中...
          </>
        ) : (
          <>
            <Upload className="mr-2 h-4 w-4" />
            选择文件
          </>
        )}
      </Button>
    </div>
  );
}
