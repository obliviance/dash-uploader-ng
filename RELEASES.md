# Release log

What happened when each version was shipped: dates, the CI run that gated it,
what was actually verified and how, and anything that went wrong.

This is the maintainer's record. For **what changed** in each version, see
[`docs/CHANGELOG.md`](docs/CHANGELOG.md). The two are kept separate on purpose —
see [`docs/BRANCHING.md`](docs/BRANCHING.md#changelogmd-vs-releasesmd).

Newest first.

---

## 1.2.0 — 2026-08-26

Bug fixes and performance only; no new features.

| | |
| --- | --- |
| Tag | [`v1.2.0`](https://github.com/obliviance/dash-uploader-ng/releases/tag/v1.2.0) |
| PyPI | [dash-uploader-ng 1.2.0](https://pypi.org/project/dash-uploader-ng/1.2.0/) |
| Released from | `main` @ `_RELEASE_SHA_` |
| Gating CI run | `_RELEASE_RUN_` |
| Publish method | PyPI Trusted Publishing (OIDC, no API token) |

**Headline:** large-upload throughput. The completeness check `stat()`ed all N
chunks on every request — O(N²) syscalls, roughly 131 million `stat()` calls
for the 11.2 GB file in upstream #102.

**Verified**

- 182 headless tests on Python 3.10, 3.11, 3.12, 3.13.
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
