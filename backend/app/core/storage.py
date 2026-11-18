"""Storage abstraction. Rendering always happens on local disk (FFmpeg needs files);
final artifacts are mirrored to S3/R2 when STORAGE_BACKEND=s3."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.core.config import settings

log = logging.getLogger(__name__)


class Storage:
    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("path escapes storage root")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def key_for(self, path: str | Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    @staticmethod
    def sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def mirror(self, key: str) -> str | None:
        """Upload an artifact to S3/R2 if configured. Returns the object URL/key or None."""
        if settings.storage_backend != "s3" or not settings.s3_bucket:
            return None
        import boto3  # optional dependency path

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            region_name=settings.s3_region or None,
        )
        client.upload_file(str(self.path(key)), settings.s3_bucket, key)
        log.info("mirrored %s to s3://%s", key, settings.s3_bucket)
        return f"s3://{settings.s3_bucket}/{key}"


storage = Storage()
