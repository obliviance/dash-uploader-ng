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

- [`tests/test_upstream_parity.py`](tests/test_upstream_parity.py) —
  **differential tests** that run this fork's handler and the *pristine
  upstream handler* (vendored at `tests/_upstream/`) over the same requests and
  diff the results. Legitimate traffic must behave identically; hostile traffic
  must not.

The first three run headless: `pytest` (no browser required). Upstream's
Selenium suite lives in `tests/browser/` and also passes — see
[Compatibility](#compatibility-with-dash-uploader) below.

## What is actually exploitable, per vector

Measured by running the real upstream code, not inferred from the advisory:

| Vector | Upstream behaviour | This fork |
| --- | --- | --- |
| `upload_id` traversal | **200 OK, writes outside the upload root** — the RCE primitive | 400, nothing written |
| `flowIdentifier` traversal | Writes outside the root, but only **observably on an incomplete upload** — a completed one `rmtree()`s the evidence | 400, nothing written |
| `flowFilename` traversal | **500** — dies on `FileNotFoundError` before it can escape; a denial of service, not an arbitrary write | 200, flattened to a bare filename inside the root |

Two things worth knowing here. The `flowIdentifier` vector looks harmless if
you test it with a single-chunk upload, because the escaped directory is the
temp chunk directory and upstream deletes it on completion — declare more
chunks than you send and the escaped file simply stays. And the advisory is
*more* pessimistic than the code for `flowFilename`: that one crashes rather
than writing anywhere.

## Compatibility with dash-uploader

The fork is a drop-in for everything a real flow.js client sends. Verified two
ways:

- **Upstream's own browser suite passes** — 7 passed, 1 skipped (upstream's own
  Windows-only marker), against Chromium in headless mode, including a real
  end-to-end file upload through the browser.
- **Differential tests** confirm byte-identical results to upstream for
  single-chunk, multi-chunk, re-upload, empty, binary, and non-ASCII
  (`données.csv`, `отчет.csv`, `報告書.xlsx`) uploads, with and without
  `use_upload_id`.

### Deliberate behaviour changes

These are the cases where the fork does **not** match upstream. All are pinned
by tests so they cannot drift silently.

1. **Stricter `upload_id`.** Values upstream accepted are now rejected with a
   400: spaces (`my session`), colons (`session:42`), non-ASCII (`café`),
   leading dots (`.hidden`), trailing dots (`session.`). uuid1/uuid4 — what
   `du.Upload()` generates by default — are unaffected. If your app passes its
   own `upload_id`, map it to `[A-Za-z0-9._-]` starting with an alphanumeric
   first. The alternative was hand-reasoning about which "harmless" oddities
   compose into a traversal on which filesystem.
2. **Errors are real HTTP errors.** Upstream logged the exception and returned
   `None`, which Flask rejected as an invalid response — so failures surfaced
   as an accidental 500, and the `abort()` calls inside `_get` were swallowed
   and became 500s too. Malformed requests are now 400, genuine faults 500, and
   `_get`'s 404 is a 404.
3. **`post_after` / `get_after` run on success only.** A failing request now
   propagates as an HTTP error response instead of being swallowed, so those
   hooks no longer fire on failure. Override `post`/`get` if you need a hook
   that runs either way.
4. **A path in `flowFilename` is flattened, not fatal.** Upstream 500s; the
   fork strips the directory part and saves the bare filename.

## Reporting a vulnerability

Report through **GitHub**, which is the channel a human actually monitors:

- Preferred, for anything sensitive: open a private security advisory at
  <https://github.com/obliviance/dash-uploader-ng/security/advisories/new>
- Otherwise: <https://github.com/obliviance/dash-uploader-ng/issues>

Please don't route security reports to the package metadata. `Claude
(Anthropic)` is credited as a maintainer for the work on this fork, but it is
an AI assistant and cannot receive or triage reports; **Awwab Mahdi** is the
human maintainer. Nothing sensitive should be sent anywhere but the two links
above.
