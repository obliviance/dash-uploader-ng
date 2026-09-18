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
   :func:`safe_filename` refuse anything that cannot be one path component --
   empty, a separator, ``.``/``..``, a null or control character, or too long
   for the filesystem. This layer stops the attack at the door and produces a
   useful 400 instead of a mystery.

2. **Re-check the resolved path before writing.** :func:`ensure_within`
   resolves both the upload root and the candidate path and refuses anything
   that lands outside the root. This is the backstop for what layer 1 does not
   model -- a symlink inside the upload tree, a surprising unicode
   normalisation, or a future refactor that assembles a path some other way and
   forgets to sanitise an input.

**Layer 2 is the one that actually has to hold**, and it is unconditional. That
is why layer 1 does not need a narrow character allow-list: an earlier version
of this module required ``[A-Za-z0-9._-]``, which bought no additional safety
over ``ensure_within`` and rejected a great deal of traffic upstream accepted --
``upload_id`` values derived from an e-mail address or an ISO timestamp,
filenames like ``.env`` or ``aux.csv``. That allow-list is still available as
:data:`STRICT_SEGMENTS` for deployments that want the portability guarantees.
"""

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = [
    "STRICT_SEGMENTS",
    "UnsafePathError",
    "ensure_within",
    "safe_filename",
    "safe_segment",
]

# Characters that can never appear in a single path component, on any platform
# this runs on or is served from. Everything else is allowed: upstream accepted
# any string at all here, and the values apps really pass -- session e-mails,
# ISO timestamps, ids beginning with an underscore -- are harmless once they
# cannot escape the upload root. See STRICT_SEGMENTS below for the stricter
# alternative and why it is not the default.
_PATH_SEPARATORS = ("/", "\\")

# The narrow allow-list this module used to enforce unconditionally. Kept
# because it is the right rule for a deployment that also wants portability
# guarantees, but it is opt-in: it rejected a lot of traffic upstream accepted
# (session e-mails, ISO timestamps, ids starting with an underscore).
_STRICT_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: When True, ``safe_segment`` and ``safe_filename`` additionally require the
#: narrow ``[A-Za-z0-9._-]`` allow-list, reject dotfiles, reject names Windows
#: reserves for devices (``con``, ``nul``, ``aux``, ``com1`` ...) and reject
#: names ending in a dot or space (which Windows silently strips).
#:
#: The default is False, which matches upstream dash-uploader: anything that is
#: not a path separator, a traversal component or a control character is
#: accepted. Path safety does not depend on this flag -- :func:`ensure_within`
#: is the boundary that actually holds, and it is always applied.
#:
#: Turn it on if your uploads are consumed on Windows, or if a custom
#: ``http_request_handler`` validates file extensions server-side (a trailing
#: dot can slip past such a check on Windows)::
#:
#:     import dash_uploader_ng.safepath as safepath
#:     safepath.STRICT_SEGMENTS = True
STRICT_SEGMENTS = False

# ext4, APFS, NTFS and friends all cap a single path component at 255 *bytes*.
# Measuring characters instead is wrong in both directions: it rejects
# perfectly legal 201-243 character ASCII names (upstream #142), and it accepts
# a 200-character CJK name that is 600 bytes and fails at write time with an
# opaque 500.
_MAX_SEGMENT_BYTES = 255

# A filename additionally has "_part_<n>" appended to form each chunk file, so
# it needs headroom or a maximum-length upload dies on its first chunk write.
# MAX_CHUNKS is 10_000_000, so the longest suffix is "_part_10000000" -- 14
# bytes. Kept in step with httprequesthandler.MAX_CHUNKS by a test.
_CHUNK_SUFFIX_BYTES = len("_part_") + 8
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
    """Checks that apply to any single path component.

    These are the unconditional ones: a component that fails any of them either
    cannot be written to disk at all, or is a traversal primitive. The
    portability rules live in :func:`_check_strict` and are opt-in.
    """
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
    # "." and ".." are the traversal primitives themselves; no amount of
    # permissiveness makes them acceptable as a directory or file name.
    if value in (".", ".."):
        _reject(field, value, "is a path traversal component")
    if STRICT_SEGMENTS:
        _check_strict(field, value)


def _check_strict(field, value):
    """The portability rules, applied only when ``STRICT_SEGMENTS`` is on."""
    # Windows silently strips trailing dots and spaces, so "evil.py." and
    # "evil.py " both resolve to "evil.py" there -- enough to slip past any
    # extension check a caller layers on top of this.
    if value != value.rstrip(". "):
        _reject(field, value, "ends with a dot or space")
    if value.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
        _reject(field, value, "is a reserved device name on Windows")
    if value.startswith("."):
        _reject(field, value, "resolves to a dotfile")
    if not _STRICT_SEGMENT.match(value):
        _reject(
            field,
            value,
            "must be a single path segment of [A-Za-z0-9._-] starting with an "
            "alphanumeric",
        )


def safe_segment(value, field):
    """Return ``value`` if it is safe to use as one directory/file name.

    Used for ``upload_id`` and ``flowIdentifier``, both of which name a
    directory created under the upload root.

    ``upload_id`` is a *public parameter* of ``du.Upload()`` and apps routinely
    derive it from session data -- an e-mail address, an ISO timestamp, a name
    with a space in it. A narrow allow-list turned all of those into an opaque
    upload failure that upstream did not have, so what is rejected here is only
    what genuinely cannot be one path component: something empty, a path
    separator, ``.``/``..``, a null or control character, or a name too long
    for the filesystem. Set :data:`STRICT_SEGMENTS` to restore the allow-list.

    This is deliberately not the security boundary. :func:`ensure_within` is,
    and it runs on every path this module hands out regardless of this
    function's verdict.

    Raises
    ------
    UnsafePathError
        If ``value`` cannot be used as a single path segment.
    """
    _check_common(field, value)
    for separator in _PATH_SEPARATORS:
        if separator in value:
            _reject(field, value, "contains a path separator")
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

    Beyond the separator strip, what is refused is only what cannot be written:
    an empty name, ``.``/``..``, null or control characters, or a name too long
    for the filesystem once ``_part_<n>`` is appended. Names that are merely
    awkward -- ``.env``, ``aux.csv``, ``report.csv.`` -- are accepted, as they
    were upstream. Set :data:`STRICT_SEGMENTS` to refuse them.

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
    for separator in _PATH_SEPARATORS:
        if separator in name:
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

    # `Path.relative_to` rather than `Path.is_relative_to`: the latter is 3.9+,
    # and this package supports older interpreters. `relative_to` has the same
    # semantics here (it returns "." for the root itself) and raises ValueError
    # for anything outside.
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError:
        raise UnsafePathError(
            f"resolved path {str(candidate_resolved)!r} escapes the upload root "
            f"{str(root_resolved)!r}"
        ) from None
    return candidate_resolved
