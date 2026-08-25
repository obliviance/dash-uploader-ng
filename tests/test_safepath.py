"""Unit tests for the path-safety layer added in this fork.

These pin the exact accept/reject behaviour of the helpers that stand between
an unauthenticated POST body and the filesystem. They are deliberately
fine-grained: the end-to-end tests in test_security_cve_2026_38360.py prove the
handler is wired up, but a regression here is where a hole would actually
reopen.
"""

import os
from pathlib import Path

import pytest

from dash_uploader_ng.safepath import (
    UnsafePathError,
    ensure_within,
    safe_filename,
    safe_segment,
)


class TestSafeSegment:
    @pytest.mark.parametrize(
        "value",
        [
            "8f14e45fceea167a5a36dedd4bea2543",  # a uuid4 hex
            "3e2f1c5a-9c4b-4e1a-9a5e-6c1f2b3d4e5f",  # a uuid4 with dashes
            "1048576-reportcsv",  # a flow.js identifier
            "session_42",
            "a.b.c",
            "A",
        ],
    )
    def test_accepts_ordinary_identifiers(self, value):
        assert safe_segment(value, field="upload_id") == value

    @pytest.mark.parametrize(
        "value",
        [
            "..",
            ".",
            "../etc",
            "../../../../usr/local/lib/python3.10/site-packages",  # the CVE PoC
            "..\\..\\..\\windows",
            "/etc/passwd",
            "C:\\windows",
            "a/b",
            "a\\b",
            ".hidden",
            "",
            "with space",
            "sub\x00dir",
            "line\nbreak",
            "trailing.",
            "trailing ",
            "CON",
            "nul.txt",
            "x" * 201,
        ],
    )
    def test_rejects_anything_that_is_not_one_boring_segment(self, value):
        with pytest.raises(UnsafePathError):
            safe_segment(value, field="upload_id")

    def test_error_names_the_field_and_does_not_replay_raw_newlines(self):
        with pytest.raises(UnsafePathError) as excinfo:
            safe_segment("evil\ndir", field="upload_id")
        message = str(excinfo.value)
        assert message.startswith("upload_id=")
        # The offending value is repr()'d, so a newline in it cannot forge an
        # extra log line.
        assert "\n" not in message


class TestSafeFilename:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("report.csv", "report.csv"),
            ("archive.tar.gz", "archive.tar.gz"),
            # flow.js sends a relative path when a folder is dropped in;
            # upstream's documented behaviour is to flatten it.
            ("subdir/report.csv", "report.csv"),
            ("a/b/c/report.csv", "report.csv"),
            # Backslashes are ordinary filename characters on Linux, but the
            # same upload handled on Windows would be traversal -- so they are
            # stripped on every platform.
            ("subdir\\report.csv", "report.csv"),
            ("..\\..\\..\\app.py", "app.py"),
            ("../../../app.py", "app.py"),
            ("C:\\Users\\me\\report.csv", "report.csv"),
            # Non-ASCII survives intact. werkzeug's secure_filename would
            # ASCII-fold these; the whole point of not using it is that
            # "données.csv" must not silently become "donnes.csv", and a fully
            # non-Latin name must not become the empty string.
            ("données.csv", "données.csv"),
            ("отчет.csv", "отчет.csv"),
            ("報告書.xlsx", "報告書.xlsx"),
        ],
    )
    def test_strips_directories_and_keeps_the_real_name(self, value, expected):
        assert safe_filename(value, field="flowFilename") == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "..",
            ".",
            "../..",
            "subdir/..",
            ".bashrc",
            "sub/.ssh",
            "evil\x00.csv",
            "evil\n.csv",
            "report.csv.",  # Windows strips the trailing dot -> "report.csv"
            "report.csv ",
            "CON.txt",
            "x" * 201,
        ],
    )
    def test_rejects_names_with_nothing_safe_left(self, value):
        with pytest.raises(UnsafePathError):
            safe_filename(value, field="flowFilename")


class TestEnsureWithin:
    def test_allows_the_root_itself(self, tmp_path):
        assert ensure_within(tmp_path, tmp_path) == tmp_path.resolve()

    def test_allows_a_path_below_the_root(self, tmp_path):
        target = tmp_path / "session" / "file.csv"
        assert ensure_within(tmp_path, target) == target.resolve()

    def test_allows_a_path_that_does_not_exist_yet(self, tmp_path):
        target = tmp_path / "not" / "created" / "yet.csv"
        assert ensure_within(tmp_path, target) == target.resolve()

    def test_rejects_a_traversal_out_of_the_root(self, tmp_path):
        root = tmp_path / "uploads"
        root.mkdir()
        with pytest.raises(UnsafePathError):
            ensure_within(root, root / ".." / "escaped.csv")

    def test_rejects_a_sibling_with_a_shared_name_prefix(self, tmp_path):
        # "uploads-evil" starts with "uploads" but is not inside it; a naive
        # str.startswith() containment check would wave this through.
        root = tmp_path / "uploads"
        root.mkdir()
        (tmp_path / "uploads-evil").mkdir()
        with pytest.raises(UnsafePathError):
            ensure_within(root, tmp_path / "uploads-evil" / "file.csv")

    def test_rejects_an_absolute_path_elsewhere(self, tmp_path):
        with pytest.raises(UnsafePathError):
            ensure_within(tmp_path, Path("/etc/passwd"))

    @pytest.mark.skipif(
        not hasattr(os, "symlink"), reason="platform has no symlink support"
    )
    def test_rejects_an_escape_that_only_exists_after_symlink_resolution(
        self, tmp_path
    ):
        # This is the case a purely lexical check on the form fields cannot
        # see, and the reason ensure_within resolves before comparing.
        root = tmp_path / "uploads"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)

        with pytest.raises(UnsafePathError):
            ensure_within(root, root / "link" / "file.csv")
