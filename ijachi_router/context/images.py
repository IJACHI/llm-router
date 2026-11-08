"""Load image files as message parts for vision-capable models."""

from __future__ import annotations

import base64
from pathlib import Path

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_IMAGE_BYTES = 5_000_000


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_TYPES


def load_image_parts(paths: list[str | Path]) -> list[dict]:
    """Session-log content parts ({"kind": "image", ...}); unreadable or oversized files are skipped."""
    parts = []
    for p in paths:
        path = Path(p)
        mt = IMAGE_TYPES.get(path.suffix.lower())
        if not mt or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            continue
        parts.append({"kind": "image", "media_type": mt, "name": path.name,
                      "data": base64.b64encode(path.read_bytes()).decode("ascii")})
    return parts
