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

from dash_uploader_ng import safepath
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
            "",
            "sub\x00dir",
            "line\nbreak",
            "x" * 256,
        ],
    )
    def test_rejects_anything_that_cannot_be_one_path_component(self, value):
        with pytest.raises(UnsafePathError):
            safe_segment(value, field="upload_id")

    @pytest.mark.parametrize(
        "value",
        [
            "user@example.com",   # session e-mail
            "2024-01-15T10:30:00",  # ISO timestamp
            "_private",           # leading underscore
            "user+tag",
            "my session",
            "sess:42",
            "caf\u00e9",
            "session.",
            ".hidden",
            "CON",
            "nul.txt",
        ],
    )
    def test_accepts_what_upstream_accepted(self, value):
        """Only traversal and un-writable components are refused.

        `ensure_within` is the boundary that holds; a narrow character
        allow-list here bought nothing and rejected a great deal of traffic
        that upstream dash-uploader handled. See STRICT_SEGMENTS.
        """
        assert safe_segment(value, field="upload_id") == value

    @pytest.mark.parametrize(
        "value", ["my session", "sess:42", "caf\u00e9", ".hidden", "session.", "CON"]
    )
    def test_strict_mode_restores_the_allow_list(self, value, monkeypatch):
        monkeypatch.setattr(safepath, "STRICT_SEGMENTS", True)
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
            "evil\x00.csv",
            "evil\n.csv",
            "x" * 242,
        ],
    )
    def test_rejects_names_with_nothing_safe_left(self, value):
        with pytest.raises(UnsafePathError):
            safe_filename(value, field="flowFilename")

    @pytest.mark.parametrize(
        "value,expected",
        [
            (".bashrc", ".bashrc"),
            ("sub/.ssh", ".ssh"),
            ("report.csv.", "report.csv."),
            ("report.csv ", "report.csv "),
            ("CON.txt", "CON.txt"),
            ("aux.csv", "aux.csv"),
            (".env", ".env"),
        ],
    )
    def test_accepts_awkward_names_upstream_accepted(self, value, expected):
        """Dotfiles, Windows device names and trailing dots are legal here.

        They are legal filenames on the platforms this normally runs on, and
        upstream wrote them without complaint. STRICT_SEGMENTS refuses them for
        deployments that need Windows portability.
        """
        assert safe_filename(value, field="flowFilename") == expected

    @pytest.mark.parametrize(
        "value", [".bashrc", "report.csv.", "report.csv ", "CON.txt", "aux.csv"]
    )
    def test_strict_mode_refuses_them(self, value, monkeypatch):
        monkeypatch.setattr(safepath, "STRICT_SEGMENTS", True)
        with pytest.raises(UnsafePathError):
            safe_filename(value, field="flowFilename")


class TestLengthLimitsAreInBytes:
    """Filesystems cap a path component at 255 *bytes*, not characters.

    Measuring characters was wrong in both directions: it rejected legal
    201-243 character ASCII names (upstream #142 territory), and it accepted a
    200-character CJK name that is 600 bytes and then failed at write time with
    an opaque 500.
    """

    def test_a_long_ascii_filename_is_accepted(self):
        # 241 bytes: the most that still leaves room for "_part_10000000".
        name = "x" * 237 + ".csv"
        assert safe_filename(name, field="flowFilename") == name

    def test_a_filename_with_no_room_for_the_chunk_suffix_is_rejected(self):
        with pytest.raises(UnsafePathError, match="bytes"):
            safe_filename("x" * 242, field="flowFilename")

    def test_a_multibyte_filename_is_measured_in_bytes(self):
        # 80 CJK characters is only 80 characters but 240 bytes; with ".csv"
        # that is 244, past the limit.
        with pytest.raises(UnsafePathError, match="bytes"):
            safe_filename("報" * 80 + ".csv", field="flowFilename")

    def test_a_short_multibyte_filename_is_fine(self):
        name = "報" * 50 + ".csv"
        assert safe_filename(name, field="flowFilename") == name

    def test_a_directory_segment_may_use_the_full_255_bytes(self):
        # No "_part_<n>" is appended to a directory name, so it gets the whole
        # budget.
        name = "a" * 255
        assert safe_segment(name, field="upload_id") == name
        with pytest.raises(UnsafePathError, match="bytes"):
            safe_segment("a" * 256, field="upload_id")

    def test_the_longest_accepted_filename_still_produces_a_writable_chunk_name(
        self, tmp_path
    ):
        """The limit has to be justified by the filesystem actually accepting it."""
        from dash_uploader_ng.httprequesthandler import MAX_CHUNKS, get_chunk_name

        name = safe_filename("x" * 237 + ".csv", field="flowFilename")
        chunk_name = get_chunk_name(name, MAX_CHUNKS)
        # Would raise OSError("File name too long") if the budget were wrong.
        (tmp_path / chunk_name).write_bytes(b"x")
        assert len(chunk_name.encode()) <= 255


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
