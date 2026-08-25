# Security

## CVE-2026-38360 — path traversal → RCE (fixed in this fork)

**Affected:** upstream `dash-uploader`, all versions `0.1.0` through `0.7.0a2`.
**Severity:** Critical — CWE-22, CVSS 3.1 score 9.8 (network / no auth / low complexity).
**Status upstream:** unpatched; the repository was archived on 2025-07-19.
**Status here:** fixed in `dash-uploader-ng` from `1.0.0` onward.

### What it was

The upload endpoint (`/API/dash-uploader` by default) took three form fields
straight off an unauthenticated `POST` and joined them onto the upload
directory without checking that the result stayed inside it:

- `upload_id` — used as a directory name under the upload root
- `flowFilename` — used as the saved file's name
- `flowIdentifier` — used as a per-upload temp directory name

A single request was enough to write outside the upload root:

```
upload_id=../../../../usr/local/lib/python3.10/site-packages
flowFilename=evil.pth
```

Writing a `.pth` file into `site-packages` turns an arbitrary file write into
**remote code execution**: Python executes `.pth` files on the next interpreter
start. Other primitives (dropping `sitecustomize.py`, overwriting a module or a
WSGI entry point, planting a script in a cron directory) get there too.

### How it's fixed

Validation happens once, at the request boundary, in
[`dash_uploader_ng/safepath.py`](dash_uploader_ng/safepath.py), in two layers:

1. **Reject bad components up front.** `upload_id` and `flowIdentifier` must be
   a single safe path segment; `flowFilename` / `flowRelativePath` have any
   directory part stripped (folder uploads are flattened, as upstream
   documented) and the remainder validated. A rejected request returns
   **HTTP 400**, not a 500.
2. **Re-check the resolved path before every write.** `ensure_within()`
   resolves the candidate and the upload root and refuses anything that lands
   outside the root — this also catches escapes that only appear after symlink
   resolution, which a purely lexical check on the form fields cannot see.

Filenames are **not** run through `werkzeug.utils.secure_filename`, on purpose:
it ASCII-folds, so it would silently turn `données.csv` into `donnes.csv` and
empty out a fully non-Latin filename. The fork strips separators and validates
the remainder instead, so real-world filenames survive intact.

The handler was also hardened against a missing/absurd `flowTotalChunks` and an
out-of-range `flowChunkNumber`, which previously crashed with a 500.

### Tests

- [`tests/test_safepath.py`](tests/test_safepath.py) — the validation helpers in
  isolation (accept/reject tables, including a symlink-escape case).
- [`tests/test_security_cve_2026_38360.py`](tests/test_security_cve_2026_38360.py)
  — the published proof of concept and variants fired at a live Flask app,
  asserting against the filesystem that nothing lands outside the upload root,
  plus regression tests that ordinary and non-ASCII uploads still work.

Both run headless: `pytest` (no browser required).

## Reporting a vulnerability

Open a private security advisory on the GitHub repository, or an issue if the
report is not itself sensitive.
