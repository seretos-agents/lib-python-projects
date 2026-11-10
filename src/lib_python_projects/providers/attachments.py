"""Image attachments for tickets and comments (ticket #304).

Compile-level skeleton: types and signatures only; behaviour is added in the
implement phase.
"""
from __future__ import annotations

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


def prepare_attachments(attachments: list[ImageAttachment]) -> list[Any]:
    raise NotImplementedError


def render_body(body: str, prepared: list[Any], urls: list[str]) -> str:
    raise NotImplementedError


def extract_image_refs(body: str) -> list[ImageAsset]:
    raise NotImplementedError
