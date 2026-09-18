# Upstream compatibility

`dash-uploader-ng` is meant to be a drop-in replacement for
[`dash-uploader`](https://github.com/fohrloop/dash-uploader): change the import,
change nothing else.

This document records a line-by-line audit of every difference between the two,
what was done about each, and the two differences that are kept on purpose.
The rendered version of this report is kept alongside it at
[`docs/drop-in-audit.html`](drop-in-audit.html), and published at
<https://claude.ai/code/artifact/4659ec70-e067-4961-96f6-2256c84bc868>.

**Audit baseline:** upstream commit
[`e1a1af4`](https://github.com/fohrloop/dash-uploader/commit/e1a1af47aa607b7aa3deceafe5c5452d98465610),
the last before the repository was archived on 2025-07-19.
**First audited:** 1.2.1. **Resolved in:** 1.3.0.

Regressions found by the audit are pinned by
[`tests/test_upstream_compatibility.py`](../tests/test_upstream_compatibility.py)
and [`tests/test_upstream_parity.py`](../tests/test_upstream_parity.py), the
latter running the vendored pristine upstream handler side by side with this
one over the same requests.

---

## Summary

| | Finding | Status |
| --- | --- | --- |
| F-01 | Python floor raised to 3.10 | ✅ lowered to 3.8 |
| F-02 | Dash floor raised to 2.0 | ✅ restored to 1.1.0 |
| F-03 | `upload_id` character set narrowed | ✅ relaxed to upstream's |
| F-04 | Filenames legal on Linux/macOS refused | ✅ relaxed to upstream's |
| F-05 | Uploads over 100,000 chunks refused | ✅ ceiling raised 100× |
| F-06 | `post_after` / `get_after` skipped on failure | ✅ restored |
| F-07 | `settings.UPLOAD_FOLDER_ROOT` became read-only | ✅ writable again |
| F-08 | Flask endpoint names changed | ✅ restored for the first uploader |
| F-09 | An extra `GET` per chunk, on by default | ✅ off by default |
| F-10 | Bundled CSS no longer leaks into the host page | ⚠️ **kept** — see below |
| F-11 | An extra class on the root element | ⚠️ **kept** — consequence of F-10 |
| F-12 | `isCompleted` prop silently dropped from `fileSuccess` | ✅ restored in 1.3.1 |
| F-13 | `completedClass` never applied (`getClass()` read `completeClass`) | ✅ fixed in 1.3.2 |

---

## Resolved

### F-01 · Python floor

`requires-python` is `>=3.8`. Upstream declared none at all, and its own
`utils.py` carried a `pkg_resources` fallback for Python < 3.8, so it was
installable well below 3.10.

The one API that had forced a higher floor was `pathlib.Path.is_relative_to`
(3.9+) in `safepath.ensure_within`; it now uses `Path.relative_to` in a
`try`/`except ValueError`, which has identical semantics here.

### F-02 · Dash floor

`dash>=1.1.0`, upstream's own value. The fork is verified working on dash 1.21
as well as dash 4.x. The only version-sensitive code — the
`dash_version_is_at_least("1.12")` guard around `prevent_initial_call` — was
already written for dash 1.x.

> Note that dash 1.x itself requires `werkzeug<2.1`. That is a constraint of
> dash 1.x, not of this package, but it is worth knowing before pinning there:
> those werkzeug releases have their own advisories.

### F-03 · `upload_id` character set

`upload_id` is a public parameter of `du.Upload()`, and apps routinely derive it
from session data. An earlier allow-list of `[A-Za-z0-9._-]` starting with an
alphanumeric turned all of these into an opaque *"Unexpected error while
uploading"*:

| value | why an app would use it |
| --- | --- |
| `user@example.com` | the session e-mail |
| `2024-01-15T10:30:00` | an ISO timestamp |
| `_private` | an internal id convention |
| `user+tag`, `my session`, `sess:42`, `café` | ordinary identifiers |

All are accepted again. `safe_segment` now refuses only what genuinely cannot be
one path component: empty, a path separator, `.`/`..`, a null or control
character, or longer than the filesystem allows.

**This costs nothing in safety.** `ensure_within` — which resolves the candidate
path and the upload root and refuses anything landing outside, symlinks
included — is the boundary that actually holds, it always ran, and it still
does. CVE-2026-38360 and its published proof of concept remain covered by
`tests/test_security_cve_2026_38360.py`.

### F-04 · Filenames

Filename handling was already generous — spaces, parentheses, commas, `&`, `%`,
`#`, quotes, brackets and full Unicode all survive intact, which is better than
`werkzeug.utils.secure_filename` manages. Four classes were refused and are now
accepted, as upstream accepted them:

- dotfiles — `.env`, `.gitignore`
- names Windows reserves for devices — `nul.txt`, `con.log`, `aux.csv`,
  `prn.pdf`, `com1.dat`, `lpt1.txt`
- names ending in a dot or a space — `report.csv.`, `report.csv `
- (`.` and `..` themselves are still refused; they are the traversal primitives)

### F-05 · Chunk-count ceiling

`MAX_CHUNKS` was 100,000 — about 100 GB at the default 1 MB chunk size, which a
deployment that raised `max_file_size` or lowered `chunk_size` could genuinely
hit and be refused for. It is now 10,000,000 (~10 TB), and the reassembly builds
its chunk paths lazily so nothing is materialised per chunk. Upstream had no
limit; this one exists only to keep `range()` from being handed something
absurd on an unauthenticated request.

### F-06 · Subclass hooks on the failure path

Upstream swallowed a failing `_post` into a `None` return, so the
`post_after()` line in its documented subclass template still ran before Flask
turned that `None` into a 500. This fork returns a real error response, which
raised straight past the hook.

`post_after` and `get_after` now run from a `finally`, so they fire on both
paths. Subclasses use them for cleanup, audit logging, metrics and lock
release — the error path is exactly when that matters.

`abort()` raised from `post_before` — the documented way to reject an
unauthorised upload — was never affected and still returns its own status.

### F-07 · `settings.UPLOAD_FOLDER_ROOT`

Upstream read this module global inside the callback on every fire, so
assigning to it after `configure_upload()` redirected the paths the callback
reported. It is the only workaround anyone has for
[upstream #17](https://github.com/fohrloop/dash-uploader/issues/17).

Resolving the folder from the registered config instead made that assignment a
silent no-op. `settings.upload_folder_root_for()` now prefers the module global
for components covered by the default configuration, and the config only for
components with a *named* one — so single-uploader apps behave as they did, and
multi-uploader apps still route correctly.

This never moved where the server *writes*; the handler captures its folder at
`decorate_server` time, upstream included.

### F-08 · Flask endpoint names

Upstream registered the upload route with `endpoint=None`, so Flask derived
`get` and `post` from the view function names. Deriving names from the API path
instead is what makes a second `configure_upload()` possible — but it broke
`app.view_functions["post"]`, `url_for("post")` and CSRF exemptions written
against upstream.

The **first** uploader on a server now keeps `get` / `post`. Only a second and
subsequent one falls back to `dash_uploader_ng_<slugified api path>_get` /
`_post`, since those names are taken by then. Every app that could have worked
upstream is a single-uploader app, so every such app keeps the old names.
See [deployment.md](deployment.md#csrf-protection).

### F-09 · Resumable uploads are opt-in

`resumable` defaults to `False`, matching upstream's hard-coded
`testChunks: false`. With it on, each chunk costs an extra `GET` to the upload
endpoint — about a thousand for a 1 GB upload — which a proxy, WAF or rate
limiter tuned against upstream was never configured for.

Turn it on with `du.Upload(id=..., resumable=True)`. See
[resumable-uploads.md](resumable-uploads.md).

### F-12 · `isCompleted` prop

`Upload_ReactComponent`'s `fileSuccess` handler updated `dashAppCallbackBump`
and the file-name/size props on every successful upload, but never set
`isCompleted` — upstream's own boolean prop for "this file just finished" —
and it was not declared in `propTypes` at all, so it never reached the
generated Python component. Apps hooking a completion transition to
`isCompleted` as an `Input`/`State` never saw it fire, even though anything
driven by `dashAppCallbackBump` kept working, which is what let it go
unnoticed: the upload logs, the row just never turns ready.

Restored to match upstream: `isCompleted` is declared in
`propTypes`/`defaultProps`, set `True` on `fileSuccess`, and reset to `False`
when the next upload starts. Fixed in 1.3.1; see
[RELEASES.md](../RELEASES.md#131--2026-09-18).

This entry did not exist when this audit first ran (1.2.1 → 1.3.0) — the
"Verified identical" claim below that "React prop surface: `resumable`
added, none removed" was checked at the declaration/behavior level for the
props the audit's own test corpus exercised, and `isCompleted` fell through
that gap because nothing in the corpus asserted on it. Recorded here as a
correction to that claim, not just a new finding.

### F-13 · `completedClass` never applied

`getClass()` read `this.props.completeClass` to decide whether to add the
"upload complete" CSS class to the root element, but the prop is declared and
defaulted everywhere else as `completedClass`. `completeClass` was never
declared, so the read was always `undefined`, and the documented
`completedClass` prop never did anything.

This is upstream's own bug, byte-for-byte the same typo at `e1a1af4` — not
something this fork introduced. It stayed invisible because `isComplete` (the
state flag gating this line) was `false` until F-12 was fixed, so the branch
never ran; once F-12 shipped, it ran on every successful upload, pushing
`undefined` into the class array. `Array.prototype.join` renders `undefined`
as an empty string, so the only visible effect was a stray space in the
rendered `className` — never a broken class name, and never the string
`"undefined"`.

Unlike F-10/F-11, restoring this costs nothing in drop-in compatibility: the
prop's own documentation already promised this behavior, upstream just never
delivered it, so no app could have been relying on `completedClass` actually
working. Fixed in 1.3.2 by reading `completedClass` instead of `completeClass`.

---

## Kept on purpose

### F-10 · The bundled CSS no longer leaks · F-11 · An extra root class

These two are one decision.

Upstream shipped fragments of Bootstrap 4 inside `button.css` and
`progressbar.css` with unscoped selectors — `.btn`, `.progress`, and a bare
`progress` *element* selector — injected into `<head>`. Importing the component
therefore restyled buttons and progress elements across the whole host
application, which is
[upstream #91](https://github.com/fohrloop/dash-uploader/issues/91) (breaks Font
Awesome) and [#43](https://github.com/fohrloop/dash-uploader/issues/43)
(restyles unrelated buttons).

Every rule is now scoped beneath `.dash-uploader-root`, which the component adds
to its own root element alongside whatever `className` you set.

**Why this one is not reverted toward upstream.** Every other item on this page
restores behaviour an app might depend on. This one is a bug whose "behaviour"
is *damage to code that has nothing to do with this component* — restoring it
would mean deliberately reintroducing a defect that breaks host applications.
All 241 rules in `button.css` are preserved verbatim and verified rule-for-rule,
so the component itself renders identically; only the leak is gone.

**What this changes for you.** If your app's own buttons or progress bars were
picking up Bootstrap styling from dash-uploader — knowingly or not — they will
render unstyled after the upgrade. Import Bootstrap properly if you want it
back.

**And F-11.** The root element's class attribute is now
`dash-uploader-root dash-uploader-default` rather than
`dash-uploader-default`. Scoping requires it. Exact-match selectors and
assertions need to become membership checks:

```python
# before
assert el.get_attribute("class") == "dash-uploader-default"
# after
assert "dash-uploader-default" in el.get_attribute("class").split()
```

---

## `STRICT_SEGMENTS`

The narrow allow-list from F-03 and F-04 is still available. It is the right
rule for a deployment that needs Windows portability guarantees, or that
validates file extensions server-side in a custom `http_request_handler` (a
trailing dot can slip past such a check on Windows, because Windows strips it):

```python
import dash_uploader_ng.safepath as safepath

safepath.STRICT_SEGMENTS = True
```

With it on, `upload_id` and filenames must match `[A-Za-z0-9._-]` starting with
an alphanumeric, dotfiles are refused, Windows device names are refused, and
names ending in a dot or space are refused.

Path safety does not depend on this flag either way — `ensure_within` is
unconditional.

---

## Verified identical

Compared directly, not assumed. Behavioural claims were established by running
both handlers over the same requests.

- `__init__.py`, `utils.py`, `uploadstatus.py` — byte-identical once the package
  rename is undone
- `__all__` unchanged: `configure_upload`, `callback`, `HttpRequestHandler`,
  `Upload`, `UploadStatus`
- Every public signature gained only trailing keyword arguments with defaults —
  `Upload(…, resumable=False)`, `callback(…, state=None)`,
  `configure_upload(…, upload_component_ids=None)`
- `UploadStatus.__init__` signature and attributes unchanged
- React prop surface: as of 1.3.1, `resumable` and `isCompleted` added, none
  removed. (Between 1.3.0 and 1.3.1 this claim was wrong: `isCompleted` had
  been dropped without being declared, so it was invisible to a props-surface
  diff done at the declaration level rather than by tracing every setProps
  call. See F-12.)
- `index.js`, `Button.react.js`, `ProgressBar.react.js` byte-identical
- CSS: 241 / 10 / 3 rules in, 241 / 10 / 3 out — none dropped, none added, no
  declaration altered
- Files land in identical paths for every `use_upload_id` × `upload_id`
  combination, including the empty-id edge case
- Reassembled bytes identical: happy path, out-of-order chunks, retry, re-upload
- Several `du.Upload` components under one `configure_upload()` all resolve to
  the same endpoint
- `prevent_initial_call` logic and the callback's `Input`/`State` order
  unchanged; extra `State` appended last
- Legacy globals still populated: `settings.app`, `UPLOAD_FOLDER_ROOT`,
  `upload_api`, both pathname prefixes
- `du.Upload()` before `du.configure_upload()` still renders with the default
  endpoint rather than raising
- Runtime JS dependencies unchanged — flow.js 2.14.1, lodash, ramda

## Method

Upstream was cloned at `e1a1af4` and every shared file diffed after normalising
`dash_uploader_ng` back to `dash_uploader`. Behavioural claims come from running
both handlers in Flask test clients over the same corpus: 18 `upload_id` values,
28 filenames, both `use_upload_id` modes, four chunk counts, a failing `_post`,
and an `abort()` from `post_before`.

CSS was compared rule-by-rule rather than line-by-line — comments stripped,
selector lists split, declarations sorted, the `.dash-uploader-root` prefix
removed, then the two rule sets diffed as multisets.

Not covered: behaviour on Windows and macOS hosts, and Dash versions other than
the 1.21 and 4.x used here.

**Revisited for 1.3.2** with a genuine function-by-function read of
`Upload_ReactComponent.react.js` against upstream's source (not just its
minified bundle), rather than a props/behavior-level comparison. That is what
surfaced F-12 and F-13: the HTTP-handling layer already had this depth of
scrutiny via `test_upstream_parity.py`'s differential testing; the JS
component did not, and both findings lived specifically in code paths no test
on either side exercised. The rest of the audit's claims above were
independently re-verified at this pass and stand — including redoing the CSS
rule comparison programmatically rather than trusting the earlier count.
