# tests/test_apply_patch.py

"""Tests for the CommaMatrix text patch tool and filesystem policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from commamatrix.builtin.apply_patch import (
    PatchError,
    apply_patch_text,
    apply_update,
    parse_patch,
)
from commamatrix.utils import (
    PathResolutionError,
    read_text_file,
    resolve_path,
    write_text_file,
)


def test_parse_patch_with_add_update_delete_and_move():
    operations = parse_patch(
        "*** Begin Patch\n"
        "*** Add File: added.txt\n"
        "+created\n"
        "*** Update File: old.txt\n"
        "*** Move to: renamed.txt\n"
        "@@ function hint\n"
        " old\n"
        "-value\n"
        "+new value\n"
        "*** Delete File: removed.txt\n"
        "*** End Patch\n"
    )

    assert [operation.action for operation in operations] == ["add", "update", "delete"]
    assert operations[1].move_to == "renamed.txt"
    assert operations[1].hunks[0].context_lines == ["function hint"]


def test_apply_update_requires_eof_hunk_to_reach_end():
    hunks = parse_patch(
        "*** Begin Patch\n"
        "*** Update File: file.txt\n"
        "@@\n"
        "-middle\n"
        "+changed\n"
        "*** End of File\n"
        "*** End Patch\n"
    )[0].hunks

    with pytest.raises(PatchError, match="file end"):
        apply_update("first\nmiddle\nlast\n", hunks)


def test_apply_update_adds_at_end_for_eof_hunk():
    hunks = parse_patch(
        "*** Begin Patch\n"
        "*** Update File: file.txt\n"
        "@@\n"
        "+tail\n"
        "*** End of File\n"
        "*** End Patch\n"
    )[0].hunks

    assert apply_update("first\n", hunks) == "first\ntail\n"


def test_insertions_with_extra_context_indentation_are_applied(tmp_path: Path):
    target = tmp_path / "append.txt"
    target.write_text("строка A\nстрока B\nстрока C\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: append.txt\n"
        "@@\n"
        "  строка A\n"
        "+строка A2 (новая)\n"
        "+строка A3 (еще новая)\n"
        "  строка B\n"
        "+строка B2 (новая)\n"
        "  строка C\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path)

    assert result.succeeded
    assert target.read_text(encoding="utf-8") == (
        "строка A\n"
        "строка A2 (новая)\n"
        "строка A3 (еще новая)\n"
        "строка B\n"
        "строка B2 (новая)\n"
        "строка C\n"
    )


def test_exact_context_with_leading_space_precedes_fallback(tmp_path: Path):
    target = tmp_path / "indented.txt"
    target.write_text(" leading\nunchanged\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: indented.txt\n"
        "@@\n"
        "  leading\n"
        "-unchanged\n"
        "+changed\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path)

    assert result.succeeded
    assert target.read_text(encoding="utf-8") == " leading\nchanged\n"


def test_ambiguous_hunk_is_rejected_without_changing_file(tmp_path: Path):
    target = tmp_path / "same.txt"
    target.write_text("same\nsame\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: same.txt\n"
        "@@\n"
        "-same\n"
        "+changed\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path)

    assert not result.succeeded
    assert result.operations[0].status == "failed"
    assert "ambiguous" in result.error
    assert target.read_text(encoding="utf-8") == "same\nsame\n"


def test_patch_preflight_failure_reports_all_files_without_partial_write(tmp_path: Path):
    target = tmp_path / "existing.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: existing.txt\n"
        "@@\n"
        "-old\n"
        "+new\n"
        "*** Update File: missing.txt\n"
        "@@\n"
        "-old\n"
        "+new\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path)

    assert not result.succeeded
    assert [operation.status for operation in result.operations] == [
        "not applied",
        "failed",
    ]
    assert target.read_text(encoding="utf-8") == "old\n"


def test_move_rejects_existing_destination(tmp_path: Path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("old\n", encoding="utf-8")
    destination.write_text("existing\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: source.txt\n"
        "*** Move to: destination.txt\n"
        "@@\n"
        "-old\n"
        "+new\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path)

    assert not result.succeeded
    assert "destination already exists" in result.error
    assert source.read_text(encoding="utf-8") == "old\n"
    assert destination.read_text(encoding="utf-8") == "existing\n"


def test_patch_preserves_bom_and_crlf(tmp_path: Path):
    target = tmp_path / "formatted.txt"
    target.write_bytes(b"\xef\xbb\xbffirst\r\nsecond\r\n")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: formatted.txt\n"
        "@@\n"
        " first\n"
        "-second\n"
        "+changed\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path)

    assert result.succeeded
    assert target.read_bytes() == b"\xef\xbb\xbffirst\r\nchanged\r\n"
    assert read_text_file(target).file_format.encoding == "utf-8-sig"
    assert read_text_file(target).file_format.newline == "\r\n"


def test_resolver_rejects_escape_and_absolute_paths(tmp_path: Path):
    with pytest.raises(PathResolutionError, match="escapes"):
        resolve_path("../outside.txt", root=tmp_path)
    with pytest.raises(PathResolutionError, match="absolute"):
        resolve_path(str(tmp_path / "outside.txt"), root=tmp_path)


def test_absolute_paths_can_be_enabled(tmp_path: Path):
    target = tmp_path / "outside.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n"
        "@@\n"
        "-old\n"
        "+new\n"
        "*** End Patch\n"
    )

    result = apply_patch_text(patch, root=tmp_path / "workspace", allow_absolute=True)

    assert result.succeeded
    assert target.read_text(encoding="utf-8") == "new\n"


def test_write_text_file_preserves_existing_format(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")

    write_text_file(target, "one\nthree\n")

    assert target.read_bytes() == b"\xef\xbb\xbfone\r\nthree\r\n"
