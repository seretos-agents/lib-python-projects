"""GitHub image attachments (ticket #304): mocked HTTP via MockTransport."""
from __future__ import annotations

import base64
import json
import re

import httpx
import pytest

from lib_python_projects import ProjectConfig
from lib_python_projects.providers import github as github_provider
from lib_python_projects.providers.attachments import (
    AttachmentRejected,
    ImageAsset,
    ImageAttachment,
)
from lib_python_projects.providers.github import GitHubProvider

BASE = "/repos/acme/backend"
PNG_A = b"\x89PNG\r\n-bytes-A\x00\xff"
PNG_B = b"\xff\xd8JPEG-bytes-B\x00"
BLOB = "https://github.com/acme/backend/blob/ticket-attachments/"


def _project() -> ProjectConfig:
    return ProjectConfig(
        id="acme", provider="github", path="acme/backend", token_env="T",
    )


def _issue(number=7, body="", labels=()):
    return {
        "number": number, "title": "t", "body": body, "state": "open",
        "user": {"login": "bot"}, "assignees": [],
        "labels": [{"name": n} for n in labels],
        "html_url": f"https://github.com/acme/backend/issues/{number}",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "node_id": "N",
    }


class Fake:
    """Tiny GitHub fake recording every request and its decoded JSON body."""

    def __init__(self, monkeypatch, *, push=True, branch_exists=True,
                 issue_body="", raw_files=None):
        self.push = push
        self.branch_exists = branch_exists
        self.issue_body = issue_body
        self.raw_files = raw_files or {}
        self.seen: list[httpx.Request] = []
        self.puts: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []
        self.patches: list[tuple[str, dict]] = []
        transport = httpx.MockTransport(self._handle)

        def fake_client(token):
            return httpx.Client(
                base_url=github_provider.API_BASE,
                headers={"Accept": "application/vnd.github+json",
                         "Authorization": f"Bearer {token}"},
                transport=transport,
            )

        monkeypatch.setattr(github_provider, "_client", fake_client)

    @staticmethod
    def _j(payload, status=200):
        return httpx.Response(status, json=payload)

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        path, m = req.url.path, req.method
        body = json.loads(req.content) if req.content and m != "GET" else {}
        if m == "GET" and path == BASE:
            return self._j({"default_branch": "main",
                            "permissions": {"push": self.push}})
        if m == "GET" and path == f"{BASE}/git/ref/heads/ticket-attachments":
            if self.branch_exists:
                return self._j({"object": {"sha": "att-sha"}})
            return self._j({"message": "Not Found"}, 404)
        if m == "GET" and path == f"{BASE}/git/ref/heads/main":
            return self._j({"object": {"sha": "main-sha"}})
        if m == "POST" and path == f"{BASE}/git/refs":
            self.posts.append((path, body))
            return self._j({"ref": body.get("ref")}, 201)
        if m == "PUT" and path.startswith(f"{BASE}/contents/"):
            self.puts.append((path, body))
            rel = path[len(f"{BASE}/contents/"):]
            return self._j({"content": {
                "path": rel,
                "html_url": BLOB + rel,
            }}, 201)
        if m == "GET" and path.startswith(f"{BASE}/contents/"):
            rel = path[len(f"{BASE}/contents/"):]
            if rel in self.raw_files:
                return httpx.Response(200, content=self.raw_files[rel])
            return self._j({"message": "Not Found"}, 404)
        if path.startswith(f"{BASE}/labels"):
            return self._j({"name": "x"}, 201 if m == "POST" else 200)
        if m == "POST" and path == f"{BASE}/issues":
            self.posts.append((path, body))
            return self._j(_issue(7, body.get("body", ""), body.get("labels", [])), 201)
        if m == "POST" and re.fullmatch(rf"{BASE}/issues/\d+/comments", path):
            self.posts.append((path, body))
            return self._j({"id": 55, "body": body.get("body", ""),
                            "user": {"login": "bot"},
                            "html_url": "https://github.com/acme/backend/issues/7#c55",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z"}, 201)
        if m == "GET" and path == f"{BASE}/issues/comments/55":
            return self._j({"id": 55, "body": self.issue_body,
                            "user": {"login": "bot"}, "html_url": "",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z"})
        if m == "GET" and re.fullmatch(rf"{BASE}/issues/\d+", path):
            return self._j(_issue(7, self.issue_body))
        if m == "GET" and re.fullmatch(rf"{BASE}/issues/\d+/(comments|timeline)", path):
            return self._j([])
        if m == "PATCH" and re.fullmatch(rf"{BASE}/issues/\d+", path):
            self.patches.append((path, body))
            return self._j(_issue(7, body.get("body", self.issue_body)))
        return self._j([], 200)

    def writes(self):
        return [r for r in self.seen if r.method in ("PUT", "POST", "PATCH", "DELETE")]


def _files(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(PNG_A)
    b = tmp_path / "b.jpg"
    b.write_bytes(PNG_B)
    return a, b


def _create(**kw):
    body = kw.pop("body", "hello")
    return GitHubProvider().create_ticket(_project(), "tok", "title", body, [], [], **kw)


# ---------- R1 ----------------------------------------------------------------


def test_create_ticket_uploads_and_references_in_order(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    a, b = _files(tmp_path)
    _create(attachments=[ImageAttachment(a, "first"), ImageAttachment(b)])

    assert len(fake.puts) == 2
    (pa, ba), (pb, bb) = fake.puts
    assert re.fullmatch(rf"{BASE}/contents/attachments/[0-9a-f]+/a\.png", pa)
    assert re.fullmatch(rf"{BASE}/contents/attachments/[0-9a-f]+/b\.jpg", pb)
    assert base64.b64decode(ba["content"]) == PNG_A
    assert base64.b64decode(bb["content"]) == PNG_B
    assert ba["branch"] == "ticket-attachments"

    methods = [(r.method, r.url.path) for r in fake.writes()]
    assert methods[-1] == ("POST", f"{BASE}/issues")
    assert [m for m, _ in methods[:-1]].count("PUT") == 2

    issue_body = fake.posts[-1][1]["body"]
    url_a = BLOB + pa.split("/contents/")[1] + "?raw=true"
    url_b = BLOB + pb.split("/contents/")[1] + "?raw=true"
    ia = issue_body.index(f"![first]({url_a})")
    ib = issue_body.index(f"![b.jpg]({url_b})")
    assert ia < ib


def test_create_ticket_bootstraps_branch_when_missing(monkeypatch, tmp_path):
    fake = Fake(monkeypatch, branch_exists=False)
    a, _ = _files(tmp_path)
    _create(attachments=[ImageAttachment(a)])
    order = [(r.method, r.url.path) for r in fake.writes()]
    assert order[0] == ("POST", f"{BASE}/git/refs")
    assert fake.posts[0][1] == {"ref": "refs/heads/ticket-attachments", "sha": "main-sha"}
    assert order[1][0] == "PUT"


def test_create_ticket_idempotent_replay_uploads_nothing(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    a, _ = _files(tmp_path)
    key = "k-304-replay"
    _create(attachments=[ImageAttachment(a)], idempotency_key=key)
    assert len(fake.puts) == 1
    _create(attachments=[ImageAttachment(a)], idempotency_key=key)
    assert len(fake.puts) == 1


# ---------- R2 end to end -------------------------------------------------------


def test_create_ticket_rewrites_local_ref(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "shot.png").write_bytes(PNG_A)
    _create(body="see ![x](./shot.png)", attachments=[ImageAttachment("shot.png")])
    issue_body = fake.posts[-1][1]["body"]
    assert "./shot.png" not in issue_body
    assert re.search(
        r"see !\[x\]\(https://github\.com/acme/backend/blob/ticket-attachments/"
        r"attachments/[0-9a-f]+/shot\.png\?raw=true\)",
        issue_body,
    )
    # referenced file is not appended a second time
    assert issue_body.count("shot.png") == 1


# ---------- R3 ------------------------------------------------------------------


def test_add_comment_with_attachment(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    a, _ = _files(tmp_path)
    GitHubProvider().add_comment(
        _project(), "tok", "7", "", attachments=[ImageAttachment(a, "pic")],
    )
    assert len(fake.puts) == 1
    comment_body = fake.posts[-1][1]["body"]
    assert f"![pic]({BLOB}attachments/" in comment_body
    assert comment_body.rstrip().endswith("?raw=true)")


def test_update_ticket_with_attachment(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    a, _ = _files(tmp_path)
    GitHubProvider().update_ticket(
        _project(), "tok", "7", body="new body", attachments=[ImageAttachment(a)],
    )
    assert len(fake.puts) == 1
    sent = fake.patches[-1][1]["body"]
    assert f"![a.png]({BLOB}attachments/" in sent
    assert "new body" in sent


def test_update_ticket_attachments_without_body_rejected(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    a, _ = _files(tmp_path)
    with pytest.raises(ValueError):
        GitHubProvider().update_ticket(
            _project(), "tok", "7", title="x", attachments=[ImageAttachment(a)],
        )
    assert fake.seen == []


# ---------- R4 ------------------------------------------------------------------


@pytest.mark.parametrize("method", ["create_ticket", "add_comment"])
@pytest.mark.parametrize("case", ["missing", "bmp", "no_push"])
def test_refusals_before_write(monkeypatch, tmp_path, method, case):
    fake = Fake(monkeypatch, push=(case != "no_push"))
    if case == "missing":
        target = tmp_path / "gone.png"
        reason = "not found"
    elif case == "bmp":
        target = tmp_path / "x.bmp"
        target.write_bytes(b"BM")
        reason = "unsupported type"
    else:
        target = tmp_path / "ok.png"
        target.write_bytes(PNG_A)
        reason = "no push access"
    att = [ImageAttachment(target)]
    with pytest.raises(AttachmentRejected) as ei:
        if method == "create_ticket":
            GitHubProvider().create_ticket(
                _project(), "tok", "t", "b", ["bug"], [], attachments=att,
            )
        else:
            GitHubProvider().add_comment(_project(), "tok", "7", "b", attachments=att)
    assert reason in ei.value.reason
    assert str(ei.value.path) == str(target)
    assert fake.writes() == []
    if case != "no_push":
        assert fake.seen == []


def test_uppercase_extension_accepted(monkeypatch, tmp_path):
    fake = Fake(monkeypatch)
    p = tmp_path / "SHOT.PNG"
    p.write_bytes(PNG_A)
    _create(attachments=[ImageAttachment(p)])
    assert len(fake.puts) == 1


# ---------- R5 ------------------------------------------------------------------

_REF = BLOB + "attachments/u/a.png?raw=true"


def test_list_ticket_images(monkeypatch):
    Fake(monkeypatch, issue_body=f"x ![one]({_REF}) y ![two](https://h/b.png)")
    out = GitHubProvider().list_ticket_images(_project(), "tok", "7")
    assert out == [ImageAsset("one", _REF), ImageAsset("two", "https://h/b.png")]


def test_list_comment_images(monkeypatch):
    Fake(monkeypatch, issue_body=f"![c]({_REF})")
    out = GitHubProvider().list_ticket_images(_project(), "tok", "7", comment_id="55")
    assert out == [ImageAsset("c", _REF)]


def test_list_ticket_images_img_tag(monkeypatch):
    Fake(monkeypatch, issue_body=f'<img src="{_REF}" alt="t">')
    out = GitHubProvider().list_ticket_images(_project(), "tok", "7")
    assert [a.url for a in out] == [_REF]


@pytest.mark.parametrize("url", [
    _REF,
    "https://github.com/ACME/Backend/raw/ticket-attachments/attachments/u/a.png",
    "https://raw.githubusercontent.com/acme/backend/ticket-attachments/attachments/u/a.png",
])
def test_download_image_writes_identical_bytes(monkeypatch, tmp_path, url):
    fake = Fake(monkeypatch, raw_files={"attachments/u/a.png": PNG_A})
    dest = tmp_path / "out.png"
    result = GitHubProvider().download_image(_project(), "tok", url, dest)
    assert dest.read_bytes() == PNG_A
    assert str(result) == str(dest)
    (req,) = fake.seen
    assert req.method == "GET"
    assert req.url.path == f"{BASE}/contents/attachments/u/a.png"
    assert req.url.params["ref"] == "ticket-attachments"
    assert req.headers["Accept"] == "application/vnd.github.raw+json"


@pytest.mark.parametrize("url", [
    "https://github.com/other/repo/blob/ticket-attachments/attachments/u/a.png",
    "https://evil.example.com/acme/backend/blob/x/a.png",
    "https://raw.githubusercontent.com/other/repo/main/a.png",
])
def test_download_image_rejects_foreign_url(monkeypatch, tmp_path, url):
    fake = Fake(monkeypatch)
    with pytest.raises(ValueError) as ei:
        GitHubProvider().download_image(_project(), "tok", url, tmp_path / "o.png")
    assert url in str(ei.value)
    assert fake.seen == []
    assert not (tmp_path / "o.png").exists()
