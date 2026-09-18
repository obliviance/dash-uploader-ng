# Release log

What happened when each version was shipped: dates, the CI run that gated it,
what was actually verified and how, and anything that went wrong.

This is the maintainer's record. For **what changed** in each version, see
[`docs/CHANGELOG.md`](docs/CHANGELOG.md). The two are kept separate on purpose —
see [`docs/BRANCHING.md`](docs/BRANCHING.md#changelogmd-vs-releasesmd).

Newest first.

---

## 1.3.2 — 2026-09-18

Bug fix (F-13) and three performance improvements, no new features.

| | |
| --- | --- |
| Status | **Published** |
| Tag | `v1.3.2` @ `0db2a2b` (pushed 2026-09-18) |
| PyPI | ✅ https://pypi.org/project/dash-uploader-ng/1.3.2/ (wheel + sdist) |
| Released from | `main` @ `0db2a2b` |
| Gating CI run | [`35397858403`](https://github.com/obliviance/dash-uploader-ng/actions/runs/35397858403) (release branch, 10/10 green) and [`35398089360`](https://github.com/obliviance/dash-uploader-ng/actions/runs/35398089360) (publish: full matrix + upstream browser suite, all green); `stable` fast-forwarded to `0db2a2b` automatically |
| Publish method | PyPI Trusted Publishing (OIDC, no API token) |

**Headline:** `getClass()` in `Upload_ReactComponent` read the undeclared
`completeClass` instead of the actual `completedClass` prop, so the
documented "upload complete" CSS class never applied — upstream's own typo,
faithfully inherited, invisible until the 1.3.1 `isCompleted` fix made the
gating branch reachable. Fixed by reading `completedClass`. Full detail in
[docs/upstream-compatibility.md#f-13--completedclass-never-applied](docs/upstream-compatibility.md#f-13--completedclass-never-applied).

**Also:** a performance review of the request-handling and component code
found three small, verified-safe wins, all pinned by the existing test
suite rather than just asserted: a no-op `os.utime()` call on each chunk's
lock file removed (nothing ever reads its mtime); the per-chunk
`.exists()` check before `mkdir()` replaced with `mkdir(exist_ok=True)`,
dropping a `stat()` that succeeded on every chunk after the first; and
`Upload_ReactComponent.state.uploadedFiles` now reset at the start of each
upload batch instead of accumulating for the component's entire lifetime.
None change behavior — `tests/test_performance.py`'s syscall-counting suite
passed before and after.

Two further findings from that review were deliberately **not** acted on:
`ensure_within()` re-resolves the same session/chunk-folder path multiple
times per chunk, which is real but touches the code CVE-2026-38360's fix
depends on being unconditional, so it needs benchmarking and a
security-conscious look rather than a quick edit; and chunk-then-copy
reassembly does a full second read+write pass over every uploaded byte,
where writing directly at each chunk's offset would roughly halve disk I/O
but needs a different completeness-tracking mechanism entirely. Both are
real candidates for a future release, not this one.

**Post-publish smoke test**, against the wheel actually installed from PyPI
in a clean virtualenv (run from outside the repo, as usual, so the
installed package is what's imported): version `1.3.2`; `_post`'s source
confirmed no `os.utime()` call and `mkdir(..., exist_ok=True)` present; the
bundled JS confirmed `uploadedFiles:[]` reset present in
`onFilesSubmitted`'s `setState` call (not just the initial state).

**Note on the index:** as with 1.3.0, the aggregate PyPI JSON endpoint and
the simple index pip reads both briefly still reported `1.3.1` as latest
immediately after the publish workflow finished, while the version-specific
endpoint (`/pypi/dash-uploader-ng/1.3.2/json`) already served `1.3.2`
correctly. Caught up within a couple of minutes; not a publish failure.

## 1.3.1 — 2026-09-18

Single-bug patch release.

| | |
| --- | --- |
| Status | **Published** |
| Tag | `v1.3.1` @ `63adcc8` (pushed 2026-09-18) |
| PyPI | ✅ https://pypi.org/project/dash-uploader-ng/1.3.1/ (wheel + sdist) |
| Released from | `main` @ `63adcc8` |
| Gating CI run | [`35376036357`](https://github.com/obliviance/dash-uploader-ng/actions/runs/35376036357) (release branch, green) and [`35376400735`](https://github.com/obliviance/dash-uploader-ng/actions/runs/35376400735) (publish: 3.10-3.13 + upstream browser suite, all green); `stable` fast-forwarded to `63adcc8` automatically |
| Publish method | PyPI Trusted Publishing (OIDC, no API token) |

**Headline:** `Upload_ReactComponent`'s `fileSuccess` handler updated
`dashAppCallbackBump` and the file-name/size props on every successful upload,
but never set `isCompleted` — upstream's own boolean prop for "this file just
finished" — and the prop was not even declared in `propTypes`, so it never
reached the generated Python component at all. An app hooking a "file ready"
row/status transition to `isCompleted` (as an `Input` or `State`) never saw it
fire, while anything driven by `dashAppCallbackBump` — including a logging
callback — kept working, which is what made the regression easy to miss:
upload logged, row never turns ready.

Root-caused by diffing `fileSuccess` against upstream's real distributed
bundle (`dash_uploader-0.6.1`'s `dash_uploader.min.js`), which confirmed
upstream calls `setProps({fileNames, isCompleted: true})` and
`setState({isComplete: true, ...})` on every file success, and resets both to
`false` on the next `fileAdded`. `git log -p` on
`Upload_ReactComponent.react.js` showed `isComplete` had been `false` since
the file's original import (`e538278`) and was never set anywhere afterward —
so this was present from the ng rewrite, not introduced by a later commit.

**Post-publish smoke test**, against the wheel actually installed from PyPI in
a clean virtualenv (run from outside the repo so the installed package is
what's imported, not the working tree): version `1.3.1`; `isCompleted` present
in `Upload_ReactComponent`'s `available_properties` and settable/gettable as a
real prop on the instantiated component.

**Known gap, not addressed here:** there is still no JS-level parity check for
this component (the vestigial `src/lib/tests/Upload_ReactComponent.test.js`
imports `@testing-library/react` and `jest`, neither of which is a
dependency, and CI never runs a JS test step) — only `tests/test_upstream_parity.py`
covers the HTTP-handling layer this way. Left as a follow-up rather than
folded into this patch.

## 1.3.0 — 2026-09-10

Drop-in compatibility with upstream `dash-uploader`.

| | |
| --- | --- |
| Status | **Published** |
| Tag | `v1.3.0` @ `6754d98` (pushed 2026-09-10) |
| PyPI | ✅ https://pypi.org/project/dash-uploader-ng/1.3.0/ (wheel + sdist) |
| Released from | `main` @ `6754d98` |
| Gating CI run | [`34526051362`](https://github.com/obliviance/dash-uploader-ng/actions/runs/34526051362) (main, 10/10 green) and [`34526311075`](https://github.com/obliviance/dash-uploader-ng/actions/runs/34526311075) (publish); `stable` fast-forwarded to `6754d98` automatically |
| Publish method | PyPI Trusted Publishing (OIDC, no API token) |

**Headline:** a line-by-line audit against upstream at `e1a1af4` — every shared
Python module, JS file and stylesheet — found eleven places the fork had stopped
being a drop-in replacement. Nine are fixed here. Where a choice existed, the
option closer to upstream won.

The two that are not reverted are the CSS scoping and the extra root class, and
they are one decision: un-scoping would deliberately reintroduce `up#91` /
`up#43`, Bootstrap 4 fragments leaking into `<head>` and restyling the host
application. Every other finding restores behaviour an app might depend on; that
one's "behaviour" is damage to unrelated code.

Full write-up: [`docs/upstream-compatibility.md`](docs/upstream-compatibility.md),
rendered at [`docs/drop-in-audit.html`](docs/drop-in-audit.html).

**Nothing here weakens the CVE-2026-38360 fix.** The relaxed input validation
was never the security boundary — `ensure_within` is, it was always
unconditional, and it still is. The published proof of concept and five
traversal variants were re-run against the relaxed code: all blocked, nothing
written outside the upload root.

**Verified:**

- 229 headless tests on Python **3.8, 3.9, 3.10, 3.11, 3.12, 3.13** — the floor
  moved down two versions this release.
- The same 229 against **dash 1.x** as well as dash 4.x, via a new
  `Oldest supported dash` CI job, so the restored `dash>=1.1.0` floor is proven
  rather than asserted.
- Upstream's Selenium browser suite.
- Differential suite against the vendored pristine upstream handler, including
  the new `TestOddButHarmlessIdentifiers` — the `upload_id` values that used to
  be refused now have to produce the same status, the same bytes, in the same
  place as upstream.
- `npm audit` clean; wheel and sdist build and `twine check` clean.

**New in the test suite:** `tests/test_upstream_compatibility.py`, 16 tests
pinning what a single request/response diff cannot see — subclass hook ordering
on the failure path, Flask endpoint names, `settings.UPLOAD_FOLDER_ROOT`
remaining writable, the chunk ceiling, and the default traffic shape.

**Post-publish smoke test**, against the wheel actually installed from PyPI in a
clean virtualenv: version `1.3.0`, `requires_python >=3.8`, `dash>=1.1.0`;
`resumable` defaults to `False`; endpoints named `get` / `post`; uploads with
`upload_id` values `user@example.com`, `_private` and `2024-01-15T10:30:00` and
filenames `.env`, `aux.csv`, `report.csv.` all return 200 and land in the right
place; 250,000 chunks accepted; the CVE proof of concept still refused with 400
and nothing written outside the upload root.

**Note on the index:** the per-version PyPI JSON endpoint served `1.3.0`
immediately, but the simple index that pip reads lagged by a couple of minutes.
Not a problem, just don't panic at a `No matching distribution found` right
after a publish.

## 1.2.1 — 2026-09-10

Single-bug patch release.

| | |
| --- | --- |
| Status | **Published** |
| Tag | `v1.2.1` @ `a37b59c` (pushed 2026-09-10) |
| PyPI | ✅ https://pypi.org/project/dash-uploader-ng/1.2.1/ (wheel + sdist) |
| Released from | `main` @ `a37b59c` |
| Gating CI run | [`34518892464`](https://github.com/obliviance/dash-uploader-ng/actions/runs/34518892464) — all jobs green; `stable` fast-forwarded to `a37b59c` automatically |
| Publish method | PyPI Trusted Publishing (OIDC, no API token) |

The GitHub Actions problem that blocked `1.2.0` had cleared by the time this
was tagged: the `Publish to PyPI` workflow ran on the `v1.2.1` tag on the first
try — tested on 3.10–3.13, ran upstream's browser suite, published via Trusted
Publishing, and fast-forwarded `stable`.

**Headline:** a resumable upload (`resumable=True`, the default) that was
interrupted *after* its last chunk landed but before reassembly would, on
resume, be reported complete by flow.js without a single `POST` — and the
`POST` handler was the only place chunks were combined, so the upload
"succeeded" with no file on disk. The chunk-test `GET` for the final chunk now
runs the same completeness check and assembly.

This is also the first release to actually reach PyPI since `1.1.0` — `1.2.0`
was tagged but its publish workflow never ran (see below), so `1.2.1` supersedes
it and carries all of the `1.2.0` changes too.

**Also in this release:** `js-yaml` pinned to `>= 4.3.2` via `overrides` to
clear GHSA-2883-xcg3-v3hh, a new advisory against the copy `eslint` pulls in.
Build tooling only.

**Verified:**

- 187 headless tests on Python 3.10–3.13, six of them new and specific to this
  bug (`tests/test_resumable.py::TestResumeAssemblesTheFile`).
- Upstream parity suite unchanged: an uninterrupted upload is byte-for-byte
  identical to before, and the O(N²) syscall regression test still holds.
- Upstream's Selenium browser suite.
- `npm audit` back to zero.
- Full flow.js request-sequence simulation (test-GET protocol + POST) against
  both this handler and the vendored pristine upstream handler: happy path,
  retry, re-upload, and the previously-broken all-chunks-present resume.

## 1.2.0 — 2026-08-26

Bug fixes and performance only; no new features.

| | |
| --- | --- |
| Status | **Tagged, publication pending** — see *Blocked* below |
| Tag | `v1.2.0` @ `7e26ded` (pushed 2026-08-26) |
| PyPI | ❌ not yet published |
| Released from | `main` @ `7e26ded` |
| Gating CI run | none — GitHub Actions did not create a run for this commit |
| Publish method | PyPI Trusted Publishing (OIDC, no API token) |

> ### ⚠️ Blocked: GitHub Actions stopped creating runs
>
> The `v1.2.0` tag is pushed and the release is fully prepared, but the publish
> workflow **never started**, so nothing reached PyPI. The same thing happened
> to the `main` push at `7e26ded` immediately before it: zero workflow runs for
> either ref.
>
> Ruled out: both workflows report `state=active`, the tag exists on the remote,
> and the identical setup ran successfully seven times earlier the same day —
> the last at 14:12 UTC for `8971840`.
>
> Not ruled out, and the most likely cause: the account's Actions
> usage/spending limit. When it is reached, GitHub silently stops creating runs
> rather than failing them.
>
> This could not be worked around from here. Dispatching the workflow needs
> `actions: write`, which the available token does not have (HTTP 403), and
> publishing by hand is impossible by design — Trusted Publishing only issues
> credentials to a GitHub Actions run, and no PyPI API token exists in this
> environment.
>
> **To finish the release:** check Actions usage under
> *Settings → Billing → Actions*, then re-run the workflow from the Actions tab,
> or delete and re-push the tag. `stable` will fast-forward itself once the
> publish succeeds.

**Headline:** large-upload throughput. The completeness check `stat()`ed all N
chunks on every request — O(N²) syscalls, roughly 131 million `stat()` calls
for the 11.2 GB file in upstream #102.

**Verified** — locally, since CI never ran:

- 182 headless tests on Python 3.10, 3.11, 3.12, 3.13 (each in its own venv).
- Wheel and sdist built and `twine check`ed clean.
- Upstream's Selenium browser suite: 7 passed, 1 skipped (its own Windows-only
  marker), against Chromium 151.
- Performance measured against the vendored pristine upstream handler on
  identical workloads: 2.1× faster at 800 chunks, 3.7× at 2000, **6.8× at
  4000**. Upstream scales quadratically (20× chunks → 115× time), the fork
  linearly (20× → 19.5×). Out-of-order uploads, the worst case for the new
  fast path, are 3.1× faster and still correct.
- The performance tests count syscalls rather than wall time, so they are not
  flaky on shared CI, and were validated against the upstream handler: it makes
  400 `os.path.exists` calls for one mid-upload chunk where the fork's
  threshold is under 20.
- Filename byte limits checked against the real filesystem, including that the
  longest accepted filename still produces a writable `_part_<n>` chunk name.

**Investigated and deliberately not "fixed"**

- `up#120` (adds an empty line to files) — not reproducible; byte-identical
  output for text, CRLF and binary payloads.
- `up#151` (invalid prop on 0.7.0a2) — not reproducible on this fork.
- `up#101` (division by zero) — already fixed upstream, inherited.
- `up#12` / `up#75` / `up#114` (multi-file queue) — left alone. The check
  already inspects the whole queue, so the real cause needs a browser
  reproduction across separate drops that the current suite cannot construct.
  Patching blind was judged worse than leaving it.

**Not covered by any run**

- The Windows file-locking path (`test_uploadtwice02`), skipped by upstream's
  own `ON_NIX` marker.
- Any browser other than Chromium 151.
- `up#30` (extremely large files) should improve for the same reason as
  `up#102` but was not independently measured.

---

## 1.1.0 — 2026-08-26

First release driven by [`ROADMAP.md`](ROADMAP.md).

| | |
| --- | --- |
| Tag | [`v1.1.0`](https://github.com/obliviance/dash-uploader-ng/releases/tag/v1.1.0) |
| PyPI | [dash-uploader-ng 1.1.0](https://pypi.org/project/dash-uploader-ng/1.1.0/) |
| Released from | `main` @ `f363af3` |
| Gating CI run | [32974363843](https://github.com/obliviance/dash-uploader-ng/actions/runs/32974363843) |
| Publish method | PyPI Trusted Publishing |

**Verified**

- 170 headless tests on Python 3.10–3.13, plus upstream's browser suite
  (7 passed, 1 skipped).
- Installed from PyPI into a clean 3.12 venv and confirmed end to end: two
  uploaders resolving distinct endpoints, `resumable` defaulting on, `state=`
  registering, the shipped bundle carrying the CSS scoping class, and the
  CVE-2026-38360 fix still live.

**What went wrong**

- The first post-publish check reported PyPI still on 1.0.0. This was the PyPI
  JSON API's cache, not a failed upload — the workflow logs showed both
  artifacts uploading successfully, and a `Cache-Control: no-cache` re-check
  showed `['1.0.0', '1.1.0']`. **Do not conclude a publish failed from the JSON
  API alone**; check the workflow log first.

**Notes**

- Three of upstream's browser tests were changed from exact to membership
  checks on the root element's class, because the component now also carries
  the `dash-uploader-root` scoping class. This is the one place upstream's
  tests were modified rather than the fork's code.

---

## 1.0.0 — 2026-08-25

First release of the fork. Upstream `dash-uploader` was archived 2025-07-19 at
`0.7.0-a2` with an unpatched critical vulnerability.

| | |
| --- | --- |
| Tag | [`v1.0.0`](https://github.com/obliviance/dash-uploader-ng/releases/tag/v1.0.0) |
| PyPI | [dash-uploader-ng 1.0.0](https://pypi.org/project/dash-uploader-ng/1.0.0/) |
| Released from | `main` @ `efb2842` |
| Gating CI run | [32967024179](https://github.com/obliviance/dash-uploader-ng/actions/runs/32967024179) |
| Publish method | PyPI Trusted Publishing (pending publisher, first upload) |

**Headline:** fixes [CVE-2026-38360](SECURITY.md), a path traversal → RCE
(CVSS 9.8) that upstream never patched.

**Verified**

- 115 headless tests on Python 3.10–3.13; wheel and sdist both installed into
  clean venvs and rendered a working Dash app.
- Upstream's own Selenium suite passes against the fork, including a real
  end-to-end browser upload.
- Differential tests run the fork's handler and the pristine upstream handler
  side by side, asserting byte-identical results for legitimate traffic.

**What went wrong / was corrected during preparation**

- Every documented example was broken on modern Dash (`dash_html_components`,
  `app.run_server()`), including the PyPI landing page's quickstart.
- The PyPI badges pointed at *upstream's* package, so the project page would
  have shown someone else's version and download counts.
- Deprecated licence metadata (a 2027 removal date) and a `MANIFEST.in` that
  referenced `LICENSE` when the file is `LICENSE.txt`.
- Writing the differential tests corrected three assumptions that had been
  asserted rather than measured — see
  [`SECURITY.md`](SECURITY.md#what-is-actually-exploitable-per-vector) for the
  per-vector table that replaced them.

**Not covered by any run**

- The Windows file-locking path, and any browser other than Chromium 151.
