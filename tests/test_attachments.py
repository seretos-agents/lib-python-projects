"""Pure-logic tests for `providers/attachments.py` (ticket #304)."""
from __future__ import annotations

import pytest

from lib_python_projects.providers.attachments import (
    AttachmentRejected,
    AttachmentUnsupported,
    ImageAsset,
    ImageAttachment,
    extract_image_refs,
    prepare_attachments,
    render_body,
)


def _make(tmp_path, name, data=b"\x89PNGdata"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_render_body_rewrites_local_ref_and_appends_rest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make(tmp_path, "shot.png")
    _make(tmp_path, "other.png")
    prepared = prepare_attachments(
        [ImageAttachment("shot.png"), ImageAttachment("other.png")]
    )
    out = render_body(
        "see ![x](./shot.png)\nmore", prepared, ["https://u/shot", "https://u/other"]
    )
    assert out.startswith("see ![x](https://u/shot)\nmore")
    assert out.endswith("![other.png](https://u/other)")
    assert out.count("![") == 2
    assert "./shot.png" not in out


def test_render_body_ref_without_dot_slash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make(tmp_path, "shot.png")
    prepared = prepare_attachments([ImageAttachment("shot.png")])
    out = render_body("a ![x](shot.png) b", prepared, ["https://u/shot"])
    assert out == "a ![x](https://u/shot) b"


def test_render_body_absolute_ref_and_foreign_ref_untouched(tmp_path):
    p = _make(tmp_path, "shot.png")
    prepared = prepare_attachments([ImageAttachment(p)])
    body = f"![a]({p.as_posix()}) ![y](https://x/y.png)"
    out = render_body(body, prepared, ["https://u/shot"])
    assert out == "![a](https://u/shot) ![y](https://x/y.png)"


def test_prepare_alt_defaults_to_file_name_and_uppercase_ext_ok(tmp_path):
    p = _make(tmp_path, "SHOT.PNG")
    prepared = prepare_attachments([ImageAttachment(p)])
    out = render_body("", prepared, ["https://u/s"])
    assert "![SHOT.PNG](https://u/s)" in out


def test_prepare_missing_file_rejected(tmp_path):
    missing = tmp_path / "nope.png"
    with pytest.raises(AttachmentRejected) as ei:
        prepare_attachments([ImageAttachment(missing)])
    assert "not found" in ei.value.reason
    assert str(ei.value.path) == str(missing)
    assert "nope.png" in str(ei.value)


def test_prepare_bad_type_rejected(tmp_path):
    p = _make(tmp_path, "x.bmp")
    with pytest.raises(AttachmentRejected) as ei:
        prepare_attachments([ImageAttachment(p)])
    assert "unsupported type" in ei.value.reason


def test_attachment_unsupported_is_not_implemented_error():
    exc = AttachmentUnsupported("create_ticket", "gitlab")
    assert isinstance(exc, NotImplementedError)
    assert exc.operation == "create_ticket" and exc.provider == "gitlab"


def test_extract_image_refs_markdown_and_img_tag_in_order():
    body = (
        'intro ![one](https://h/a.png "t") text <img src="https://h/b.png" alt="two"> '
        "![three](https://h/c.png)"
    )
    refs = extract_image_refs(body)
    assert [r.url for r in refs] == [
        "https://h/a.png", "https://h/b.png", "https://h/c.png",
    ]
    assert refs[0] == ImageAsset(alt="one", url="https://h/a.png")
    assert refs[1].alt == "two"


def test_extract_image_refs_none():
    assert extract_image_refs("no images [link](http://x)") == []
