import { useEffect, useState } from "react";
import { fetchDocumentDownloadBlob, fetchDocumentImageBlob } from "@/api/knowledge-base";
import { cn } from "@/lib/utils";
import { ImageOff } from "lucide-react";

interface AuthenticatedImageProps {
  kbId: string;
  docId: string;
  /** 后端返回的相对 URL，如 /api/v1/knowledge-bases/.../images/xxx.png */
  imageUrl?: string | null;
  alt?: string;
  className?: string;
}

/** 解析 imageUrl，提取图片文件名或判定为 download 模式 */
function resolveImageSource(imageUrl: string): { mode: "image"; name: string } | { mode: "download" } | null {
  if (imageUrl.includes("/download")) {
    return { mode: "download" };
  }
  const match = imageUrl.match(/\/images\/([^/?#]+)$/);
  if (match?.[1]) {
    return { mode: "image", name: decodeURIComponent(match[1]) };
  }
  return null;
}

export function AuthenticatedImage({
  kbId,
  docId,
  imageUrl,
  alt = "文档图片",
  className,
}: AuthenticatedImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!imageUrl) {
      setLoading(false);
      return;
    }

    let revoked = false;
    let objectUrl: string | null = null;

    const load = async () => {
      setLoading(true);
      setError(false);
      try {
        const source = resolveImageSource(imageUrl);
        if (!source) {
          setError(true);
          return;
        }
        const blob =
          source.mode === "download"
            ? await fetchDocumentDownloadBlob(kbId, docId)
            : await fetchDocumentImageBlob(kbId, docId, source.name);
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch {
        if (!revoked) setError(true);
      } finally {
        if (!revoked) setLoading(false);
      }
    };

    void load();

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [kbId, docId, imageUrl]);

  if (!imageUrl) return null;

  if (loading) {
    return (
      <div
        className={cn(
          "flex h-32 items-center justify-center rounded-md border bg-muted/20 text-xs text-muted-foreground",
          className,
        )}
      >
        加载图片…
      </div>
    );
  }

  if (error || !blobUrl) {
    return (
      <div
        className={cn(
          "flex h-32 flex-col items-center justify-center gap-1 rounded-md border bg-muted/20 text-xs text-muted-foreground",
          className,
        )}
      >
        <ImageOff className="h-5 w-5" />
        <span>图片加载失败</span>
      </div>
    );
  }

  return (
    <img
      src={blobUrl}
      alt={alt}
      className={cn("max-h-96 max-w-full rounded-md border bg-muted/20 object-contain", className)}
    />
  );
}
