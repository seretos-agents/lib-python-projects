"""Live GitHub round trip for image attachments (ticket #304).

Skipped unless LIB_PYTHON_PROJECTS_LIVE_GITHUB_TOKEN and
LIB_PYTHON_PROJECTS_LIVE_GITHUB_REPO (owner/repo) are set.
"""
from __future__ import annotations

import os
import struct
import zlib

import pytest

from lib_python_projects import ProjectConfig
from lib_python_projects.providers.attachments import ImageAttachment
from lib_python_projects.providers.github import GitHubProvider

_TOKEN = "LIB_PYTHON_PROJECTS_LIVE_GITHUB_TOKEN"
_REPO = "LIB_PYTHON_PROJECTS_LIVE_GITHUB_REPO"

pytestmark = [pytest.mark.live, pytest.mark.timeout(180)]


def _png(color: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"\x00" + color * 4
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def live():
    token, repo = os.environ.get(_TOKEN), os.environ.get(_REPO)
    missing = [n for n, v in ((_TOKEN, token), (_REPO, repo)) if not v]
    if missing:
        pytest.skip(f"live GitHub test needs env var(s): {', '.join(missing)}")
    project = ProjectConfig(id="live", provider="github", path=repo, token_env=_TOKEN)
    return GitHubProvider(), project, token


def test_live_ticket_round_trip(live, tmp_path):
    prov, project, token = live
    data = _png(b"\xff\x00\x00")
    img = tmp_path / "shot.png"
    img.write_bytes(data)
    ticket = prov.create_ticket(
        project, token, "lib-python-projects live attachment test (#304)",
        "automated round trip", [], [], attachments=[ImageAttachment(img, "shot")],
    )
    try:
        (asset,) = prov.list_ticket_images(project, token, str(ticket.id))
        out = prov.download_image(project, token, asset.url, tmp_path / "back.png")
        assert out.read_bytes() == data
    finally:
        prov.update_ticket(project, token, str(ticket.id), status="closed")


def test_live_comment_round_trip(live, tmp_path):
    prov, project, token = live
    data = _png(b"\x00\xff\x00")
    img = tmp_path / "c.png"
    img.write_bytes(data)
    ticket = prov.create_ticket(
        project, token, "lib-python-projects live comment attachment test (#304)",
        "automated round trip", [], [],
    )
    try:
        comment = prov.add_comment(
            project, token, str(ticket.id), "see image",
            attachments=[ImageAttachment(img, "c")],
        )
        (asset,) = prov.list_ticket_images(
            project, token, str(ticket.id), comment_id=str(comment.id),
        )
        out = prov.download_image(project, token, asset.url, tmp_path / "back.png")
        assert out.read_bytes() == data
    finally:
        prov.update_ticket(project, token, str(ticket.id), status="closed")
