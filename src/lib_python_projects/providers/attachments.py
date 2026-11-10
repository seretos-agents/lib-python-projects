"""Image attachments for tickets and comments (ticket #304).

Pure logic, no HTTP: validating/reading local image files, rewriting a body so
it references the uploaded copies, and extracting image refs from a body.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@dataclass(frozen=True)
class ImageAttachment:
    path: str | Path
    alt: str | None = None


@dataclass(frozen=True)
class ImageAsset:
    alt: str
    url: str


class AttachmentRejected(ValueError):
    """A local attachment was refused before any write."""

    def __init__(self, path: Any, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class AttachmentUnsupported(NotImplementedError):
    """The provider cannot store image attachments."""

    def __init__(self, operation: str, provider: str) -> None:
        self.operation = operation
        self.provider = provider
        super().__init__(f"{operation} does not support image attachments on {provider}")


@dataclass(frozen=True)
class _Prepared:
    path: Path
    name: str
    alt: str
    data: bytes


def prepare_attachments(attachments: list[ImageAttachment]) -> list[_Prepared]:
    """Validate and read every attachment; raises AttachmentRejected."""
    out: list[_Prepared] = []
    for att in attachments:
        path = Path(att.path)
        if not path.is_file():
            raise AttachmentRejected(att.path, "file not found")
        if path.suffix.lower() not in _IMAGE_TYPES:
            raise AttachmentRejected(
                att.path,
                f"unsupported type {path.suffix or '(none)'!r}; "
                f"allowed: {', '.join(sorted(_IMAGE_TYPES))}",
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise AttachmentRejected(att.path, f"file not found or unreadable: {exc}") from exc
        out.append(_Prepared(path, path.name, att.alt or path.name, data))
    return out


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)((?:\s+[^)]*)?)\)")
_IMG_TAG = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["'][^>]*>""", re.IGNORECASE)
_ALT_ATTR = re.compile(r"""\balt\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


def _resolve(ref: str) -> str | None:
    try:
        return str(Path(ref).resolve())
    except (OSError, ValueError):
        return None


def render_body(body: str, prepared: list[_Prepared], urls: list[str]) -> str:
    """Rewrite local refs to uploaded URLs; append unreferenced files."""
    by_key = {str(p.path.resolve()): i for i, p in enumerate(prepared)}
    used: set[int] = set()

    def sub(m: re.Match) -> str:
        key = _resolve(m.group(2))
        idx = by_key.get(key) if key else None
        if idx is None:
            return m.group(0)
        used.add(idx)
        return f"![{m.group(1)}]({urls[idx]}{m.group(3)})"

    out = _MD_IMAGE.sub(sub, body)
    extra = [f"![{p.alt}]({urls[i]})" for i, p in enumerate(prepared) if i not in used]
    if extra:
        head = out.rstrip("\n") + "\n\n" if out.strip() else ""
        out = head + "\n".join(extra)
    return out


def extract_image_refs(body: str) -> list[ImageAsset]:
    """Markdown and <img> image refs in body order."""
    found: list[tuple[int, ImageAsset]] = []
    for m in _MD_IMAGE.finditer(body):
        found.append((m.start(), ImageAsset(m.group(1), m.group(2))))
    for m in _IMG_TAG.finditer(body):
        alt = _ALT_ATTR.search(m.group(0))
        found.append((m.start(), ImageAsset(alt.group(1) if alt else "", m.group(1))))
    found.sort(key=lambda t: t[0])
    return [a for _, a in found]
