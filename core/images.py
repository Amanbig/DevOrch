"""Load images for multimodal prompts (``@screenshot.png``)."""

import base64
import io
import mimetypes
from dataclasses import replace
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
# Providers downscale anything larger than this anyway, but bill/transfer the full file first.
MAX_IMAGE_EDGE = 1568


def downscale(data: bytes, media_type: str, max_edge: int = MAX_IMAGE_EDGE) -> tuple[bytes, str]:
    """Shrink an image so its longest side is <= ``max_edge``. Needs Pillow; otherwise a no-op.

    Animated GIFs and images already small enough are returned untouched. Large photos/screenshots
    drop from several MB (and thousands of tokens) to a few hundred KB with no visible loss for
    a vision model.
    """
    if media_type == "image/gif":
        return data, media_type
    try:
        from PIL import Image
    except ImportError:
        return data, media_type
    try:
        with Image.open(io.BytesIO(data)) as img:
            if max(img.size) <= max_edge:
                return data, media_type
            scale = max_edge / max(img.size)
            resized = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.LANCZOS,
            )
            out = io.BytesIO()
            if media_type == "image/jpeg":
                resized.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
            elif media_type == "image/webp":
                resized.save(out, "WEBP", quality=85)
            else:
                resized.save(out, "PNG", optimize=True)
                media_type = "image/png"
            smaller = out.getvalue()
            return (smaller, media_type) if len(smaller) < len(data) else (data, media_type)
    except Exception:
        return data, media_type


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
    data, media_type = downscale(data, media_type)
    image = ImageData(
        media_type=media_type, data=base64.b64encode(data).decode("ascii"), name=path.name
    )
    return image, None


def prune_old_images(messages: list, keep: int = 2) -> list:
    """Drop image payloads from all but the most recent ``keep`` image-bearing messages.

    An image is re-sent on every model call for the rest of the session, so one screenshot can
    cost thousands of tokens per call. Older images are replaced by a short text note; the model
    can ask the user to re-attach one if it still needs it. Returns a new list; the originals
    (and the stored history) are not modified.
    """
    idx = [i for i, m in enumerate(messages) if getattr(m, "images", None)]
    stale = set(idx[:-keep]) if keep > 0 else set(idx)
    if not stale:
        return messages
    pruned = []
    for i, msg in enumerate(messages):
        if i in stale:
            names = ", ".join(img.name or "image" for img in msg.images)
            note = f"\n\n[{len(msg.images)} earlier image(s) omitted to save tokens: {names}]"
            msg = replace(msg, content=msg.content + note, images=None)
        pruned.append(msg)
    return pruned
