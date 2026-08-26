"""Path-safety helpers for the client-supplied parts of an upload request.

Every value that reaches the filesystem during an upload comes from the client:
the flow.js form fields (``flowFilename``, ``flowIdentifier``) and the
``upload_id`` that the ``du.Upload`` component sends along. Upstream
dash-uploader joined all three straight onto the upload root, which is
CVE-2026-38360 (CWE-22, CVSS 9.8). The published proof of concept is a single
unauthenticated POST::

    upload_id=../../../../usr/local/lib/python3.10/site-packages

which writes an attacker-controlled file into ``site-packages``; a ``.pth``
dropped there executes on the next interpreter start, so the path traversal is
a remote code execution primitive rather than "just" an arbitrary file write.

The defence is deliberately two layers, because each one alone has a blind
spot:

1. **Reject the component up front.** :func:`safe_segment` and
   :func:`safe_filename` require each piece to be a single, boring path
   segment. This is the layer that stops the attack at the door and produces a
   useful error, and it is the layer the tests pin exact behaviour against.

2. **Re-check the resolved path before writing.** :func:`ensure_within`
   resolves both the upload root and the candidate path and refuses anything
   that lands outside the root. This is the backstop for what layer 1 does not
   model -- a symlink inside the upload tree, a surprising unicode
   normalisation, or a future refactor that assembles a path some other way and
   forgets to sanitise an input.

Layer 2 is the one that actually has to hold. Layer 1 is what makes the failure
mode a clear 400 instead of a mystery.
"""

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = [
    "UnsafePathError",
    "ensure_within",
    "safe_filename",
    "safe_segment",
]

# A path segment we are willing to create on disk. Leading character must be
# alphanumeric, which is what rules out "..", "." and dotfiles in one go.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# ext4, APFS, NTFS and friends all cap a single path component at 255 *bytes*.
# Measuring characters instead is wrong in both directions: it rejects
# perfectly legal 201-243 character ASCII names (upstream #142), and it accepts
# a 200-character CJK name that is 600 bytes and fails at write time with an
# opaque 500.
_MAX_SEGMENT_BYTES = 255

# A filename additionally has "_part_<n>" appended to form each chunk file, so
# it needs headroom or a maximum-length upload dies on its first chunk write.
# MAX_CHUNKS is 100000, so the longest suffix is "_part_100000" -- 12 bytes.
_CHUNK_SUFFIX_BYTES = len("_part_") + 6
_MAX_FILENAME_BYTES = _MAX_SEGMENT_BYTES - _CHUNK_SUFFIX_BYTES

# Windows refuses to create these names in any directory, with or without an
# extension. Checked on every platform: an upload accepted on a Linux host may
# well be rsynced to, or served from, a Windows one.
_WINDOWS_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)]
)


class UnsafePathError(ValueError):
    """A client-supplied path component was rejected.

    Callers are expected to turn this into a 4xx response. It deliberately
    subclasses ``ValueError`` rather than an HTTP exception type so that this
    module stays independent of Flask and is trivially unit-testable.
    """


def _reject(field, value, reason):
    # Truncate and repr() the offending value: it is attacker-controlled, and
    # raw newlines in it would otherwise let an attacker forge log lines.
    shown = repr(value[:64]) + ("..." if len(value) > 64 else "")
    raise UnsafePathError(f"{field}={shown} rejected: {reason}")


def _check_common(field, value, max_bytes=_MAX_SEGMENT_BYTES):
    """Checks that apply to any single path component."""
    if not value:
        _reject(field, value, "empty")
    if "\x00" in value:
        _reject(field, value, "contains a null byte")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        _reject(field, value, "contains a control character")
    encoded_length = len(value.encode("utf-8", errors="surrogatepass"))
    if encoded_length > max_bytes:
        _reject(
            field,
            value,
            f"is {encoded_length} bytes, over the {max_bytes}-byte limit for "
            "one path component",
        )
    # Windows silently strips trailing dots and spaces, so "evil.py." and
    # "evil.py " both resolve to "evil.py" there -- enough to slip past any
    # extension check a caller layers on top of this.
    if value != value.rstrip(". "):
        _reject(field, value, "ends with a dot or space")
    if value.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
        _reject(field, value, "is a reserved device name on Windows")


def safe_segment(value, field):
    """Return ``value`` if it is safe to use as one directory/file name.

    Used for ``upload_id`` and ``flowIdentifier``, both of which name a
    directory that gets created under the upload root. The accepted character
    set is intentionally narrow -- alphanumerics, dot, dash, underscore, and an
    alphanumeric first character -- because both fields are machine-generated
    in normal use (a uuid, and flow.js's ``size-scrubbedname``), so there is no
    legitimate traffic being turned away by being strict here.

    Raises
    ------
    UnsafePathError
        If ``value`` is not a single, safe path segment.
    """
    _check_common(field, value)
    if not _SAFE_SEGMENT.match(value):
        _reject(
            field,
            value,
            "must be a single path segment of [A-Za-z0-9._-] starting with an "
            "alphanumeric",
        )
    return value


def safe_filename(value, field):
    """Return the bare, safe filename contained in ``value``.

    Unlike :func:`safe_segment` this *strips* rather than rejects a directory
    prefix, because flow.js legitimately sends a relative path in
    ``flowFilename`` when the user drags in a folder, and upstream's documented
    behaviour is to flatten those into the single upload directory anyway.

    Both POSIX and Windows separators are stripped regardless of the host
    platform. That matters: ``..\\..\\..\\app.py`` is inert on Linux (backslash
    is an ordinary filename character there) but is traversal on Windows, and
    the same deployment's uploads may be handled by either.

    Unicode is preserved -- ``werkzeug.utils.secure_filename`` would be the
    obvious alternative, but it ASCII-folds, so it silently turns
    ``données.csv`` into ``donnes.csv`` and a fully non-Latin filename into the
    empty string. Stripping separators and validating the remainder keeps
    real-world filenames intact.

    Raises
    ------
    UnsafePathError
        If nothing safe remains after stripping the directory part.
    """
    if not value:
        _reject(field, value, "empty")
    if "\x00" in value:
        _reject(field, value, "contains a null byte")

    # PurePosixPath handles "/", PureWindowsPath handles both "\" and "/" plus
    # drive letters ("C:evil.py" -> "evil.py"). Applying both covers a
    # separator that is only meaningful on the *other* platform.
    name = PureWindowsPath(PurePosixPath(value).name).name

    # Stricter than a bare segment: room is reserved for the "_part_<n>" that
    # every chunk file appends.
    _check_common(field, name, max_bytes=_MAX_FILENAME_BYTES)
    if name in (".", ".."):
        _reject(field, value, "is a path traversal component")
    if not _SAFE_SEGMENT.match(name):
        # The regex is ASCII-only by design, so re-check the residual risks
        # explicitly rather than rejecting every non-ASCII filename.
        if name.startswith("."):
            _reject(field, value, "resolves to a dotfile")
        if "/" in name or "\\" in name:
            _reject(field, value, "still contains a path separator")
    return name


def ensure_within(root, candidate):
    """Return ``candidate`` resolved, having checked it stays under ``root``.

    The final gate before any mkdir/open. Both sides are fully resolved first,
    so this also catches escapes that only exist after symlink expansion --
    something a purely lexical check on the request fields cannot see.

    Raises
    ------
    UnsafePathError
        If the resolved candidate is not ``root`` itself or below it.
    """
    root_resolved = Path(root).resolve()
    candidate_resolved = Path(candidate).resolve()

    if candidate_resolved != root_resolved and not candidate_resolved.is_relative_to(
        root_resolved
    ):
        raise UnsafePathError(
            f"resolved path {str(candidate_resolved)!r} escapes the upload root "
            f"{str(root_resolved)!r}"
        )
    return candidate_resolved
