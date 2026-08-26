# Changelog

## 1.2.0 (dash-uploader-ng)

Bug fixes and performance only — no new features. Backwards compatible.

### Performance
- **Large uploads are dramatically faster** (`up#102`, and `up#30` by
  extension). Upload completeness was tested by `stat()`ing *every* chunk on
  *every* request — O(N²) syscalls, roughly 131 million `stat()` calls for the
  11.2 GB file in the upstream report. It now costs a single `stat()` for all
  but the final chunk. Measured against the original implementation: **6.8×
  faster at 4000 chunks**, and the gap widens with file size because the old
  behaviour was quadratic and the new one is linear.
- **Reassembly streams instead of buffering.** Each chunk was read whole into
  memory; peak usage now stays flat regardless of `chunk_size`.

### Fixed
- **Filename length limits are measured in bytes, not characters** (`up#142`).
  Filesystems cap a path component at 255 bytes, so the old character-based
  limit was wrong in both directions: it rejected legal 201–243 character ASCII
  filenames, and accepted an 80-character CJK filename (244 bytes) that then
  failed at write time with an opaque server error. The limit also now reserves
  room for the `_part_<n>` suffix each chunk file appends, which a
  maximum-length filename previously overflowed.
- **`upload_id` is no longer frozen to the first render** (`up#45`). The
  uploader captured it once at mount, so re-rendering with a new `upload_id`
  kept writing to the *old* folder while the callback reported the new one —
  silent misrouting rather than a visible error.
- **CSRF-protected apps can exempt the upload route** (`up#118`). Endpoint
  names are deterministic, so there is something stable to exempt. See
  [`docs/deployment.md`](deployment.md).
- **Corrected the "unlimited file size" claim** (`up#105`). `max_file_size`
  defaults to 1024 MB; the README said otherwise. Documentation was corrected
  rather than the default changed, which would be a behaviour change.

### Notes
- `up#120` ("adds an empty line to files") is **not reproducible** — output is
  byte-identical for text, CRLF and binary payloads.
- `up#151` ("invalid prop") is **not reproducible** on this fork.
- `up#101` (division by zero on a zero-byte upload) was already fixed upstream
  and is inherited.
- `up#12` / `up#75` / `up#114` (multi-file queue limits) are **not** fixed —
  they need a browser reproduction across separate drops that the current test
  suite cannot construct.

### Project
- Added [`RELEASES.md`](../RELEASES.md), a maintainer-facing release log, and
  [`docs/BRANCHING.md`](BRANCHING.md) describing the `stable` / `main` /
  short-lived-branch model. `stable` is fast-forwarded automatically, only
  after a publish succeeds.

### Tests
182 headless tests, plus upstream's Selenium suite, green on Python 3.10–3.13.

## 1.1.0 (dash-uploader-ng)

The first release driven by [ROADMAP.md](../ROADMAP.md), which distills all 93
issues and 43 pull requests from the archived upstream repository into ten
themes. Upstream issues are cited as `up#N`.

Everything here is backwards compatible. Existing single-uploader apps need no
changes.

### Added
- **Resumable uploads** (`up#40`). An upload interrupted by a network drop, a
  browser crash or a server restart resumes instead of restarting from zero. On
  by default; `du.Upload(resumable=False)` turns it off. See
  [`docs/resumable-uploads.md`](resumable-uploads.md).
- **Several `du.Upload` components in one app** (`up#35`, `up#124`, `up#127`,
  `up#106`, `up#27`). `configure_upload()` may now be called more than once,
  with `upload_component_ids` naming the components each call governs. It also
  accepts a bare `flask.Flask` server. See
  [`docs/multiple-uploaders.md`](multiple-uploaders.md).
- **Extra callback state** (`up#104`). `du.callback(state=...)` passes values
  from elsewhere in the layout to the callback alongside the `UploadStatus` —
  the target directory, the logged-in user, a token.
- **Documented CSS class reference** (`up#25`) and styling recipes, including
  centering the progress percentage (`up#81`), in
  [`docs/styling.md`](styling.md).

### Fixed
- **The bundled CSS no longer leaks into the host application** (`up#91`,
  `up#43`). `button.css` and `progressbar.css` shipped Bootstrap 4 rules with
  unscoped selectors — `.btn`, `.progress`, and a bare `progress` *element*
  selector — injected into `<head>`, so importing the component restyled
  buttons and broke icon fonts elsewhere on the page. Every bundled rule is now
  scoped beneath `.dash-uploader-root`.
- **The chunk-test endpoint works at all.** It read `request.form` while
  flow.js sends test parameters in the query string, required a `file` part
  that a GET never carries, and answered `404` for "chunk missing" — which is
  in flow.js's `permanentErrors`, so it aborted the upload rather than
  prompting a send. It now answers `204`.
- **Interrupted writes are not trusted on resume.** A chunk is only skipped
  when it has no stale lock file, matches the client's declared chunk size, and
  is non-empty. Without this, a crash-truncated chunk reassembles into a file
  that looks like a successful upload and is silently corrupt.
- **Multiple `configure_upload()` calls no longer collide.** Flask endpoint
  names are derived from the upload API path rather than the view function's
  name, which was `get`/`post` for every handler instance. Re-using an
  `upload_api` now raises an error that says what to do.

### Notes
- **Multiple outputs from `du.callback` already worked** (`up#13`) — `output`
  has always been forwarded to `app.callback`, which accepts a list. It was a
  documentation gap, and is now covered by tests.
- Three browser tests were changed from exact equality to membership when
  checking the root element's class, since the component now also carries the
  `dash-uploader-root` scoping class. This matches the convention the rest of
  that suite already used.

### Tests
170 headless tests (up from 115) plus upstream's Selenium suite, green on
Python 3.10, 3.11, 3.12 and 3.13.

## 1.0.0 (dash-uploader-ng)

First release of `dash-uploader-ng`, a maintained fork of `dash-uploader`
(archived upstream at `0.7.0-a2`, 2025-07-19).

### Security
- **Fixed [CVE-2026-38360](../SECURITY.md)** — a critical (CWE-22, CVSS 9.8)
  path-traversal → RCE in the upload endpoint. The `upload_id`, `flowFilename`
  and `flowIdentifier` form fields are now validated at the request boundary
  (`dash_uploader_ng/safepath.py`), and every resolved path is re-checked
  against the upload root before any write. Malformed requests now return a
  proper `400`/`404` instead of an accidental `500`.

### Changed
- **Renamed** the package: distribution `dash-uploader` → `dash-uploader-ng`,
  import `dash_uploader` → `dash_uploader_ng`. Update your imports; the API is
  otherwise unchanged.
- **Modernized packaging**: replaced the `package.json`-driven `setup.py` with
  a `pyproject.toml` (PEP 621). `requires-python >= 3.10`; supports Python
  3.10–3.13.
- **Dependency floor** raised to `dash>=2.0` (verified against dash 4.x).
- **Refreshed the JS build**: bumped `styled-jsx` to v5 and pruned the
  unused-at-build-time `react-scripts` and `npm` dev-dependencies. `npm audit`
  now reports **0 vulnerabilities** (was 87, incl. 5 critical). The shipped
  runtime bundle (flow.js, lodash, ramda) is unchanged in behaviour.
- **Split the test suite**: fast headless tests (`tests/`) run without a
  browser; the Selenium suite moved to `tests/browser/`.

## 0.7.0-a1 (2022-03-30)

- This pre-release is available in PyPI with `--pre` flag.
- [0.6.0 → 0.7.0 Migration Guide](https://github.com/fohrloop/dash-uploader/wiki/Migration-Guide#060--070).

### Fixed
- Calling callback each time file is uploaded in multi-file upload case (Fixes: [#5](https://github.com/fohrloop/dash-uploader/issues/5), [#20](https://github.com/fohrloop/dash-uploader/issues/20) & [#44](https://github.com/fohrloop/dash-uploader/issues/44))
- Progress bar problems when uploading multiple files (Fixes: [#84](https://github.com/fohrloop/dash-uploader/issues/84))
- Instead of returing `None`, raise `dash.exceptions.PreventUpdate`. This should reduce errors seen in the browser console. [PR 54](https://github.com/fohrloop/dash-uploader/pull/54)
- Fixed  `ImportError` which was raised when trying to import `dash_uploader_ng` when `packaging` was not installed. [PR 54](https://github.com/fohrloop/dash-uploader/pull/54)
### Changed 
- resumable.js -> flowjs (Closes: [#21](https://github.com/fohrloop/dash-uploader/issues/21))
- ⚠️ **Backwards incompatible**: Callback syntax (@du.callback) was changed to use `status` instead of `filenames` as the callback function argument. Support for `@app.callback` syntax dropped. See the [0.6.0 -> 0.7.0 Migration Guide](https://github.com/fohrloop/dash-uploader/wiki/Migration-Guide#060--070) for details.
- ⚠️**Backwards incompatible**: Changed the CSS class of the component to be `dash-uploader-completed`,  instead of `dash-uploader-complete`, when upload is completed. 

## v.0.6.0 (2021-09-19)
### Added 
- New `chunk_size`, `disabled` and `text_disabled` parameters for `du.Upload`. [Issue 41](https://github.com/fohrloop/dash-uploader/issues/41)

### Changed 
- Added the `prevent_initial_call=True` for all `du.callback`s. For [Dash >= 1.12.0](https://community.plotly.com/t/dash-v1-12-0-release-pattern-matching-callbacks-fixes-shape-drawing-new-datatable-conditional-formatting-options-prevent-initial-call-and-more/38867).

### Fixed
- Changing the parameter `disableDragAndDrop` by callbacks does not take effects. [PR 42](https://github.com/fohrloop/dash-uploader/pull/42)

## v.0.5.0 (2021-04-25)
### Added 
- [`du.HttpRequestHandler`](./dash-uploader.md#duhttprequesthandler) which allows for custom HTTP POST and GET request handling. For example, custom validation logic is now possible! Used through `http_request_handler` parameter of [`du.configure_upload`](./dash-uploader.md#duconfigure_upload).
### Changed 
- ⚠️ **Backwards incompatible changes**: Changed the CSS classes of the component to be `dash-uploader-default`, `dash-uploader-uploading`, .. etc. instead of `resumable-default`, `resumable-uploading`. 

## v.0.4.2 (2021-02-20)
- Fixed some width related CSS issues in mobile mode. See: [#19](https://github.com/fohrloop/dash-uploader/issues/19)
  
## v.0.4.1 (2020-10-27)
### Fixed
- max_files parameter to du.Upload did not have effect (Related [issue](https://github.com/fohrloop/dash-uploader/issues/12))
  
## v.0.4.0 (2020-10-27)
### Fixed
- Now dash-uploader works with `url_base_pathname` set in `app = dash.Dash(__name__, server=server, url_base_pathname='/somebase/')` . (Related [issue](https://github.com/fohrloop/dash-uploader/issues/15))
### Other
- Javascript updates (includes security updates)

## v.0.3.1 (2020-08-04)
### Fixed
- Importing `dash-uploader` with `dash` versions `<1.11.0` was not possible. (Related [issue](https://github.com/fohrloop/dash-uploader/issues/9))
### Security
- Javascript package security updates.
  
## v.0.3.0 (2020-06-06)
### Added 
- New [`@du.callback`](dash-uploader.md#ducallback) decorator for simple callback creation.   
- Experimental `max_files` parameter for `du.Upload`.
- Support for proxies; i.e. If app is running on `http://server.com/myapp`, and dash application is configured using `requests_pathname_prefix=myapp`, this is handled automatically by the Upload component. Fixes [#3](https://github.com/fohrloop/dash-uploader/issues/3).
### Fixed
- Uploading file with same name multiple times is now possible.
## v.0.2.4 (2020-06-05)
### Added
- Possibility to determine the uploader component API endpoint using the `upload_api` argument of the `configure_upload` function. 
  
## v.0.2.0 (2020-05-25)
### Added
- Upload folder for each file defined with a upload id (`upload_id`), which may be defined by the user.
### Fixed
- Uploading file with similar name now overwrites the old file (previously, file chunks were uploaded, but never merged.)
- Removed potential cause of infinite wait
  
## v.0.1.2 (2020-05-22)
### Added
- Progressbar
### Changed
- Loosened `dash` requirements;  `dash~=0.11.0` -> `dash>=1.1.0`.
- `activeStyle` replaced with `uploadingStyle`.
  
  
## v.0.1.1 (2020-05-18)
### Fixed
- Callback will now fired even multiple files are uploaded in a row. (Related [Issue](https://github.com/fohrloop/dash-uploader/issues/1))
  
## v.0.1.0 (2020-04-06)
- Initial release based on the [dash-resume-upload](https://github.com/westonkjones/dash-uploader) (0.0.4).

### Changed
- Restarted project basing on the [dash-component-boilerplate](https://github.com/plotly/dash-component-boilerplate)
- Hiding "Pause" and "Cancel" buttons when not uploading
### Added
- Clean, documented python interface for `Upload`
