# Roadmap

Derived from a full read of the archived upstream repository — all **93 issues
and 43 pull requests** ([fohrloop/dash-uploader](https://github.com/fohrloop/dash-uploader)),
open and closed alike — grouped by what they actually ask for.

Upstream issue numbers are cited as `up#N` throughout. They refer to the
archived repository, not to this one.

Two claims below were verified against the source rather than taken at face
value from the reports: the CSS leak ([theme 3](#3--css-leaks-into-the-host-app))
and the disabled resumability ([theme 6](#6--resumable-uploads)).

---

## Status

| Theme | Items | State |
| ----- | ----- | ----- |
| [Already closed out in 1.0.0](#already-closed-out-in-100) | 9 | ✅ Done |
| [3 · CSS leaks into the host app](#3--css-leaks-into-the-host-app) | 6 | ✅ Done in 1.1.0 |
| [6 · Resumable uploads](#6--resumable-uploads) | 1 | ✅ Done in 1.1.0 |
| [1 · Multiple uploaders in one app](#1--multiple-uploaders-in-one-app) | 8 | ✅ Mostly done in 1.1.0 |
| [2 · Callback flexibility](#2--callback-flexibility) | 6 | ✅ Mostly done in 1.1.0 |
| [4 · Upload straight to remote storage](#4--upload-straight-to-remote-storage) | 4 | 🔨 Next |
| [5 · Multi-file upload robustness](#5--multi-file-upload-robustness) | 7 | 📋 Planned |
| [7 · Deployment, proxies and auth](#7--deployment-proxies-and-auth) | 6 | 📋 Planned |
| [8 · Large-file throughput](#8--large-file-throughput) | 4 | ✅ Mostly done in 1.2.0 |
| [9 · Code health](#9--code-health) | 2 | 📋 Planned |
| [10 · Smaller asks](#10--smaller-asks) | 5 | 📋 Planned |

Demand is quoted as upstream comment count. It is a rough signal, and it
under-weights recent issues that never got a reply after the repo went quiet.

---

## Already closed out in 1.0.0

| Ref | Ask | How |
| --- | --- | --- |
| — | Path traversal → RCE in the upload endpoint | Never filed upstream; disclosed after archival. Fixed — see [SECURITY.md](SECURITY.md) |
| `up#74` | Remove deprecated JS packages, clear vulnerability warnings | `npm audit` 87 → 0 |
| `up#52` | CI/CD with GitHub Actions | Tests on 3.10–3.13, browser suite, Trusted Publishing |
| `up#147` | Bump loader-utils and styled-jsx | Landed independently (still open upstream) |
| `up#111` | `packaging.version.LegacyVersion` AttributeError | Resolved via the modern `dash>=2.0` floor. Also `up#126`, `up#134`, `up#152` |
| `up#93` | README install instructions don't work | Rewritten; the quickstart examples were also broken on modern Dash |
| `up#33` | Security issue in `dash_uploader.min.js` | Superseded — bundle rebuilt from a clean tree |
| `up#34` | Write a test | 115 headless + upstream's Selenium suite + differential tests |
| `up#153` | dash-uploader is archived | This fork |

---

## 1 · Multiple uploaders in one app

**8 items. The largest and longest-running cluster**, asked in some form every
year since 2020.

The blocker is architectural: `configure_upload()` registers exactly one Flask
route and stores global state in `settings.py`, so a second call clobbers the
first.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#39` (PR) | 13 | Multiple Dash **or Flask** apps for `configure_upload`; adds `upload_component_ids`, backwards compatible |
| `up#35` | 7 | Multiple `du.Upload` components on one app — one route each, no chunk collisions |
| `up#17` | 5 | Change the destination folder dynamically |
| `up#45` | 4 | `upload_id` frozen to the first component created — **fixed in 1.2.0** |
| `up#106` | 2 | Multi-page app issues |
| `up#127` | 1 | Components on different pages (works at two, breaks at three) |
| `up#27` | 1 | POST 404 with multiple Dash apps |
| `up#124` | 0 | Two uploads on one page → two folders |

**Done in 1.1.0.** Configuration moved out of module globals into a registry
keyed by component id, and Flask endpoint names are now derived from the upload
API path rather than the view function's name (which was `get`/`post` for every
handler, so a second call collided). `configure_upload()` takes
`upload_component_ids`, and accepts a bare `flask.Flask` server. See
[`docs/multiple-uploaders.md`](docs/multiple-uploaders.md).

Closes `up#35`, `up#124`, `up#127`, `up#106`, `up#27`.

**Still open here:** `up#17` (change the folder *dynamically*, after the app is
serving) needs the destination to be resolved per request rather than at
configuration time — related to theme 4's storage seam. `up#45` (`upload_id` frozen to the first component) is **fixed in 1.2.0**.

---

## 2 · Callback flexibility

**6 items.** `du.callback` is a closed box: one output, no extra inputs, no
state. Users repeatedly reach for a normal `@app.callback` and hit a wall.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#103` | 11 | Use a standard `@app.callback` with uploader props (reopened after being closed) |
| `up#13` | 10 | Multiple outputs from one upload callback |
| `up#104` | 6 | Pass additional input to the callback (e.g. a dropdown choosing the target directory) |
| `up#130` (PR) | 4 | Adds a `state` parameter to `du.callback` — implements `up#104` |
| `up#121` | 1 | Support Dash background callbacks |
| `up#119` | 1 | Incompatible with dash-extensions `DashProxy` |

**Done in 1.1.0.** `du.callback` accepts `state=` (a `State` or a sequence of
them), passed through to the callback after the `UploadStatus`. Multiple
outputs turned out to already work — `output` was always forwarded to
`app.callback`, which accepts a list — so `up#13` was a documentation gap
rather than a missing feature, and is now covered by tests.

Closes `up#104`, `up#13`.

**Still open here:** `up#103` (use a plain `@app.callback`), `up#121`
(background callbacks) and `up#119` (dash-extensions `DashProxy`).

---

## 3 · CSS leaks into the host app

**6 items — resolved in 1.1.0.**

Reported as separate mysteries over four years: broken icon fonts, restyled
buttons. They shared one cause.

> **Root cause (verified).** `button.css` was 731 lines of Bootstrap 4 carrying
> unscoped global selectors (`.btn`, `.btn-sm`, …), and webpack injects it into
> `<head>` via `style-loader`. Importing the component restyled every button on
> the page.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#81` | 10 | No way to center the progress percentage |
| `up#25` | 9 | CSS classes need documenting and stabilising |
| `up#91` | 4 | Breaks Font Awesome elsewhere in the app |
| `up#43` | 2 | `button.css` restyles unrelated buttons |
| `up#19` | 1 | Width problems on mobile |
| `up#47` | 0 | Style child elements, or supply Dash components as children |

**Done:** every bundled rule is now scoped beneath the component's own root
class, so nothing reaches the host page. See [`docs/styling.md`](docs/styling.md)
for the documented class list (`up#25`).

**Still open here:** `up#47` (custom children) needs a component API change and
is tracked with theme 2.

---

## 4 · Upload straight to remote storage

**4 items.** Every deployment on ephemeral or containerised hosting hits this:
files land on a local disk that disappears.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#90` (PR) | 5 | Direct upload to S3, deliberately Python-side only |
| `up#89` | 2 | Presigned-URL uploads straight from the browser |
| `up#125` | 1 | How to upload to an S3 bucket (never answered) |
| `up#72` | 1 | Hand the upload to a database instead of disk |

**Plan.** Introduce a storage-backend seam behind `HttpRequestHandler` — a
small interface for "where does an assembled file go" — with the local
filesystem as the default implementation. That lets S3, object stores and
databases live outside the core, and keeps `boto3` an optional extra rather
than a dependency. `up#89`'s presigned-URL design is a larger change (the
browser bypasses the server entirely) and is deferred until the seam exists.

---

## 5 · Multi-file upload robustness

**7 items.** Multi-file is still marked EXPERIMENTAL in the docstring. Much was
fixed in the 0.7.0 alphas, which never reached a stable release.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#12` | 3 | Multiple files accepted even with `max_files=1` |
| `up#76` | 2 | Folder uploads flatten — subfolders never created |
| `up#80` | 1 | Skip files already present on the server |
| `up#114` | 0 | Upload stalls after 5–6 files until Pause/Resume is clicked |
| `up#151` | 0 | "Invalid prop" errors on 0.7.0a2 |
| `up#75` | 0 | `max_files` not enforced |
| `up#69` | 0 | Test whether `simultaneousUploads > 1` works |

**Note.** `up#80` is now largely answered by resumable uploads (theme 6): with
chunk testing on, an already-present file is confirmed rather than re-sent.
`up#76` needs a product decision, not just code — upstream documented flattening
as intended behaviour while the issue treats it as a bug.

---

## 6 · Resumable uploads

**1 item — resolved in 1.1.0.** The library descends from resumable.js and
moved to flow.js *for* resumability, yet the feature shipped switched off.

> **Root cause (verified).** The component set `testChunks: false`, and the
> server's `GET` handler could not have worked if it were on. It was broken
> three ways: it read `request.form` when flow.js sends test parameters in the
> **query string**; it required a `file` part that a GET never has; and it
> returned **404** for "chunk missing", which is in flow.js's `permanentErrors`
> list and therefore *aborts the whole upload* rather than prompting a normal
> send. The handler's own comment read "this seems to be permanently disabled."

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#40` | 5 | The uploader is not actually resumable |

**Done:** all three defects fixed, chunk testing enabled, and resumed chunks are
verified by size with stale-lock detection so a half-written chunk from a crash
is re-sent rather than trusted. See [`docs/resumable-uploads.md`](docs/resumable-uploads.md).

---

## 7 · Deployment, proxies and auth

**6 items.** The upload endpoint is a bare Flask route outside Dash's own
machinery, so anything in front of the app tends to intercept it.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#3` | 9 | Path-prefix handling behind a proxy (with `up#11`, `up#15`, `up#24` — closed, but worth regression tests) |
| `up#16` | 7 | Does not work on Heroku (likely the ephemeral-filesystem problem from theme 4) |
| `up#53` | 4 | Breaks under gunicorn / uWSGI |
| `up#96` | 4 | Incompatible with DjangoDash (also `up#58`) |
| `up#131` | 1 | Connection reset behind an RStudio Connect proxy |
| `up#118` | 0 | Does not work with CSRF protection enabled |

**Plan.** `up#118` is cheap and self-contained: document the exemption and give
the route a stable, importable name so a CSRF layer can exempt it. The rest
mostly need regression tests around `requests_pathname_prefix` /
`routes_pathname_prefix`, which nothing currently covers.

---

## 8 · Large-file throughput

**4 items.** "Unlimited file size" is the README's headline claim, and it is
where the sharpest complaints land.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#105` | 4 | Default `max_file_size` silently caps uploads at 1 GB — **docs corrected in 1.2.0** |
| `up#102` | 1 | ~2 orders of magnitude slower than a file copy (11.2 GB: 8.5 s to copy, 12 m 11 s to upload) |
| `up#30` | 1 | Extremely large files fail outright |
| `up#142` | 1 | Long filenames break the upload — **fixed in 1.2.0** |

**Done in 1.2.0.** The dominant cost was not what the plan guessed. Completeness
was tested by `stat()`ing **all N chunks on every request** — O(N²) syscalls
across an upload, or roughly **131 million `stat()` calls** for `up#102`'s
11.2 GB file. Replaced with a one-`stat()` gate on the final chunk plus a single
directory listing, and reassembly now streams via `shutil.copyfileobj` instead
of reading each chunk whole.

Measured against the pristine upstream handler, same workload: **6.8× faster at
4000 chunks**, and the gap widens because upstream is quadratic (20× the chunks
cost it 115× the time) while the fork is linear (20× → 19.5×).

`up#142` and `up#105` are fixed too — see below. `up#30` should improve
substantially for the same reason as `up#102`, but is not independently
verified here.

**Still open:** `up#69` (`simultaneousUploads > 1`) is untested and remains
pinned to 1.

---

## 9 · Code health

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#22` | 8 | Refactor `Upload_ReactComponent.react.js` — filed by the maintainer, labelled enhancement + help wanted |
| `up#65` | 1 | Document how the internals work |

`up#22` is a ~750-line component that themes 1, 2, 4 and 5 all have to touch;
it is the main thing standing between this list and steady progress.
`up#65` is partly addressed — [SECURITY.md](SECURITY.md) documents the request
path in detail.

---

## 10 · Smaller asks

Self-contained and low-risk; several are close to free.

| Ref | Demand | Ask |
| --- | ------ | --- |
| `up#123` | 6 | Return only the local filepath |
| `up#10` | 2 | Delete uploaded files after a session or TTL |
| `up#86` | 2 | Cannot upload video from an iPhone |
| `up#112` | 0 | Expose the file's `lastModified` timestamp — flow.js already carries it |
| `up#148` | 0 | Uploader resets inside a Bootstrap Modal while every other component keeps state |

---

## Explicitly not planned

- **`up#4` — merge into `dash-core-components`.** Proposed in 2020, never taken
  up by Plotly, and moot now that upstream is archived.
- **`up#21` — migrate off resumable.js.** Already done: upstream moved to
  flow.js in 0.7.0, which this fork inherits.
