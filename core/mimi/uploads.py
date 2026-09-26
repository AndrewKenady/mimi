"""Uploaded attachments (photos, documents, audio) for chat, Lens and Scribe."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

from . import db as dbm
from . import log
from .auth import Ctx
from .paths import Paths

L = log.get("uploads")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
AUDIO_EXT = {".webm", ".ogg", ".opus", ".mp3", ".m4a", ".wav", ".flac", ".aac", ".mp4"}
DOC_EXT = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".html", ".htm"}
MAX_SIZE = 200 * 1024 * 1024


class UploadService:
    def __init__(self, paths: Paths):
        self.paths = paths

    def _dir(self, user_id: str) -> Path:
        d = self.paths.uploads / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, ctx: Ctx, filename: str, data: bytes, content_type: str | None = None) -> dict:
        if len(data) > MAX_SIZE:
            raise ValueError("File is too large.")
        name = re.sub(r"[^\w.\- ()]+", "_", Path(filename or "upload").name)[:120] or "upload"
        ext = Path(name).suffix.lower()
        ct = (content_type or "").lower()
        if not ext:
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "audio/webm": ".webm", "audio/ogg": ".ogg",
                   "audio/wav": ".wav", "audio/mp4": ".m4a"}.get(ct.split(";")[0], ".bin")
            name += ext
        kind = "image" if ext in IMAGE_EXT or ct.startswith("image/") else ("audio" if ext in AUDIO_EXT or ct.startswith("audio/") else ("document" if ext in DOC_EXT else "file"))
        uid = dbm.new_id("up_")
        d = self._dir(ctx.id)
        path = d / f"{uid}{ext}"
        if kind == "image":
            data = _normalise_image(data) or data
            if not ext or ext not in (".jpg", ".jpeg", ".png", ".webp"):
                path = d / f"{uid}.jpg"
        path.write_bytes(data)
        meta = {"id": uid, "user_id": ctx.id, "name": name, "kind": kind, "size": len(data), "path": str(path), "created_at": dbm.now()}
        if kind == "document":
            try:
                from .mydocs import extract_text

                meta["text"] = extract_text(path)[:40000]
            except Exception as e:
                meta["text"] = ""
                L.info("text extraction failed for %s: %s", name, e)
        (d / f"{uid}.json").write_text(json.dumps(meta), "utf-8")
        return self.public(meta)

    def get(self, ctx: Ctx, upload_id: str) -> dict | None:
        if not re.fullmatch(r"up_[0-9a-f]{16}", upload_id or ""):
            return None
        candidates = [self.paths.uploads / ctx.id / f"{upload_id}.json"]
        if ctx.is_owner:
            candidates += list(self.paths.uploads.glob(f"*/{upload_id}.json"))
        for c in candidates:
            if c.exists():
                meta = json.loads(c.read_text("utf-8"))
                meta["url"] = f"/api/uploads/{upload_id}"
                return meta
        return None

    @staticmethod
    def public(meta: dict) -> dict:
        return {"id": meta["id"], "name": meta["name"], "kind": meta["kind"], "size": meta["size"], "url": f"/api/uploads/{meta['id']}",
                "created_at": meta["created_at"]}


def _normalise_image(data: bytes) -> bytes | None:
    """Fix EXIF rotation and cap resolution so photos stay light."""
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((2400, 2400))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None
