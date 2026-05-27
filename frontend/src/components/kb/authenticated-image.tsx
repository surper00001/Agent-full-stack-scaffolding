import { useCallback, useEffect, useState } from "react";
import { fetchDocumentDownloadBlob, fetchDocumentImageBlob } from "@/api/knowledge-base";
import { cn } from "@/lib/utils";
import { ImageOff, X, ZoomIn } from "lucide-react";

interface AuthenticatedImageProps {
  kbId: string;
  docId: string;
  imageUrl?: string | null;
  alt?: string;
  className?: string;
  /** 图片原始宽度（像素），用于等比例渲染 */
  imageWidth?: number | null;
  /** 图片原始高度（像素），用于等比例渲染 */
  imageHeight?: number | null;
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
  imageWidth,
  imageHeight,
}: AuthenticatedImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lightbox, setLightbox] = useState(false);

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

  // Escape 关闭灯箱
  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightbox(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lightbox]);

  const openLightbox = useCallback(() => setLightbox(true), []);
  const closeLightbox = useCallback(() => setLightbox(false), []);

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

  // 根据原始尺寸计算渲染样式
  const hasDims = imageWidth && imageHeight && imageWidth > 0 && imageHeight > 0;
  const aspectRatio = hasDims ? imageWidth / imageHeight : undefined;
  const isVeryTall = hasDims && imageHeight / imageWidth > 3;

  const imgStyle: React.CSSProperties = {};
  if (aspectRatio !== undefined) {
    imgStyle.aspectRatio = `${imageWidth} / ${imageHeight}`;
  }

  return (
    <>
      <div className={cn("group relative", className)}>
        <img
          src={blobUrl}
          alt={alt}
          style={imgStyle}
          className={cn(
            "w-full rounded-md border bg-muted/20 object-contain",
            isVeryTall ? "max-h-[70vh]" : hasDims ? "max-h-[50vh]" : "max-h-96",
            "cursor-pointer",
          )}
          onClick={openLightbox}
        />
        <button
          type="button"
          className="absolute top-2 right-2 rounded-md bg-black/50 p-1 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={openLightbox}
          title="放大查看"
        >
          <ZoomIn className="h-4 w-4 text-white" />
        </button>
      </div>

      {/* Lightbox */}
      {lightbox && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={closeLightbox}
        >
          <button
            type="button"
            className="absolute top-4 right-4 rounded-full bg-white/10 p-2 hover:bg-white/20 transition-colors"
            onClick={closeLightbox}
            title="关闭"
          >
            <X className="h-6 w-6 text-white" />
          </button>
          <img
            src={blobUrl}
            alt={alt}
            className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
