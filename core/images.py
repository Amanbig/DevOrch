"""Load images for multimodal prompts (``@screenshot.png``)."""

import base64
import mimetypes
from pathlib import Path

from schemas.message import ImageData

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB — the strictest common provider limit


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_TYPES


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def load_image(path: Path) -> tuple[ImageData | None, str | None]:
    """Return (image, warning). The media type comes from the file's bytes, not its extension."""
    try:
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            return None, f"skipped {path.name}: {size / 1_048_576:.1f} MB exceeds the 5 MB limit"
        data = path.read_bytes()
    except OSError as e:
        return None, f"could not read {path}: {e}"
    media_type = (
        _sniff(data) or IMAGE_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path)[0]
    )
    if not media_type or not media_type.startswith("image/"):
        return None, f"skipped {path.name}: not a supported image"
    return ImageData(
        media_type=media_type, data=base64.b64encode(data).decode("ascii"), name=path.name
    ), None
