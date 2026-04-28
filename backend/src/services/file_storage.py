"""
文件存储服务。

管理知识库源文件存档：按 tenant/user/knowledge_base 隔离存储，
保留原始文件以便回溯和重新处理。
"""

import shutil
from pathlib import Path

from loguru import logger

from src.core.config import get_settings


class FileStorageService:
    """知识库文件归档服务。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_dir = Path(settings.kb_storage_dir)

    def get_kb_path(self, tenant_id: str, user_id: str, kb_id: str) -> Path:
        return self._base_dir / tenant_id / user_id / kb_id

    def get_file_dir(self, tenant_id: str, user_id: str, kb_id: str) -> Path:
        return self.get_kb_path(tenant_id, user_id, kb_id) / "files"

    def get_thumbnail_dir(self, tenant_id: str, user_id: str, kb_id: str, doc_id: str) -> Path:
        return self.get_kb_path(tenant_id, user_id, kb_id) / "thumbnails" / doc_id

    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def save_file(
        self,
        tenant_id: str,
        user_id: str,
        kb_id: str,
        doc_id: str,
        original_filename: str,
        content: bytes,
    ) -> str:
        """保存源文件，返回存储的相对路径。"""
        file_dir = self.get_file_dir(tenant_id, user_id, kb_id)
        self.ensure_dir(file_dir)

        ext = Path(original_filename).suffix.lower()
        stored_name = f"{doc_id}{ext}"
        stored_path = file_dir / stored_name
        stored_path.write_bytes(content)

        relative_path = str(
            Path(tenant_id) / user_id / kb_id / "files" / stored_name
        )
        logger.info(f"源文件已存档: {relative_path} ({len(content)} bytes)")
        return relative_path

    def save_thumbnail(
        self,
        tenant_id: str,
        user_id: str,
        kb_id: str,
        doc_id: str,
        page: int,
        idx: int,
        image_bytes: bytes,
        ext: str = "png",
    ) -> str:
        """保存缩略图/提取的图片，返回相对路径。"""
        thumb_dir = self.get_thumbnail_dir(tenant_id, user_id, kb_id, doc_id)
        self.ensure_dir(thumb_dir)

        thumb_name = f"p{page}_{idx}.{ext}"
        thumb_path = thumb_dir / thumb_name
        thumb_path.write_bytes(image_bytes)

        relative_path = str(
            Path(tenant_id) / user_id / kb_id / "thumbnails" / doc_id / thumb_name
        )
        return relative_path

    def read_file(self, stored_path: str) -> bytes:
        """读取存档文件。"""
        full_path = self._base_dir / stored_path
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(self._base_dir.resolve())):
            raise ValueError("路径穿越检测")
        if not full_path.exists():
            raise FileNotFoundError(f"文件不存在: {stored_path}")
        return full_path.read_bytes()

    def read_thumbnail(self, stored_path: str) -> bytes:
        """读取缩略图。"""
        return self.read_file(stored_path)

    def delete_kb_files(self, tenant_id: str, user_id: str, kb_id: str) -> None:
        """删除知识库下所有文件。"""
        kb_path = self.get_kb_path(tenant_id, user_id, kb_id)
        if kb_path.exists():
            shutil.rmtree(kb_path)
            logger.info(f"知识库文件已清理: {kb_path}")

    def delete_document_file(self, stored_path: str) -> None:
        """删除单个文档的存档文件。"""
        full_path = self._base_dir / stored_path
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(self._base_dir.resolve())):
            raise ValueError("路径穿越检测")
        if full_path.exists():
            full_path.unlink()

    def delete_document_assets(
        self,
        tenant_id: str,
        user_id: str,
        kb_id: str,
        doc_id: str,
        stored_path: str,
    ) -> None:
        """删除文档全部磁盘资源：源文件 + 缩略图/提取图目录。"""
        self.delete_document_file(stored_path)
        thumb_dir = self.get_thumbnail_dir(tenant_id, user_id, kb_id, doc_id).resolve()
        base = self._base_dir.resolve()
        if not str(thumb_dir).startswith(str(base)):
            raise ValueError("路径穿越检测")
        if thumb_dir.exists():
            shutil.rmtree(thumb_dir)
            logger.info(f"文档缩略图目录已清理: {thumb_dir}")

    def get_absolute_path(self, stored_path: str) -> Path:
        """获取存档文件的绝对路径（用于处理）。"""
        full_path = self._base_dir / stored_path
        return full_path.resolve()
