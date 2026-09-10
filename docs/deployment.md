# Deployment notes

Answers to the recurring "it works locally but not on my server" reports.

## CSRF protection

The upload endpoint is a plain Flask route, not a Dash callback, so a CSRF
layer intercepts it and the browser reports an upload error
([#118](https://github.com/fohrloop/dash-uploader/issues/118)). flow.js does not
send a CSRF token, so the route has to be exempted.

The first uploader registers under the endpoint names `get` and `post` — the
same names upstream dash-uploader used, so an exemption written against
upstream keeps working:

```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app.server)
du.configure_upload(app, "/data/uploads")     # /API/dash-uploader by default

csrf.exempt(app.server.view_functions["post"])
csrf.exempt(app.server.view_functions["get"])
```

If you call `configure_upload()` more than once, the *second and subsequent*
uploaders cannot reuse those names, so they get names derived from their upload
API path instead: `dash_uploader_ng_<slugified api path>_get` / `_post`. The
version that covers every uploader regardless:

```python
upload_apis = {"/API/dash-uploader", "/API/agreements"}   # yours

for rule in app.server.url_map.iter_rules():
    if rule.rule in upload_apis:
        csrf.exempt(app.server.view_functions[rule.endpoint])
```

Exempting the endpoint removes CSRF protection *from the upload route*. That
route accepts unauthenticated writes to disk by design, so if your app is
public you should be adding your own authentication with the
`http_request_handler` argument regardless — see [SECURITY.md](../SECURITY.md).

## Behind a proxy, or on a sub-path

If you set `requests_pathname_prefix` / `routes_pathname_prefix` on the Dash
app, `configure_upload()` reads them and prefixes the upload route
accordingly — this is handled for you
([#3](https://github.com/fohrloop/dash-uploader/issues/3),
[#11](https://github.com/fohrloop/dash-uploader/issues/11),
[#15](https://github.com/fohrloop/dash-uploader/issues/15),
[#24](https://github.com/fohrloop/dash-uploader/issues/24)).

What is *not* handled is the proxy itself. Two settings matter, and both
default to values that break large uploads:

- **Request body size.** nginx's `client_max_body_size` defaults to 1 MB, which
  is the same size as one default chunk — so uploads fail at or near the first
  chunk. Set it above your `chunk_size`, not above your file size: uploads are
  chunked, so the proxy only ever sees one chunk per request.
- **Timeouts.** A slow chunk can exceed `proxy_read_timeout`. The symptom is a
  connection reset mid-upload
  ([#131](https://github.com/fohrloop/dash-uploader/issues/131)).

```nginx
location / {
    proxy_pass http://127.0.0.1:8050;
    client_max_body_size 16m;   # comfortably above chunk_size
    proxy_read_timeout 300s;
}
```

## Ephemeral filesystems (Heroku, containers, serverless)

Uploads are written to the server's local disk. On a platform with an ephemeral
filesystem, that disk disappears when the dyno or container restarts, and is
not shared between instances — so a chunk can land on one instance and the next
chunk on another, and the upload never assembles
([#16](https://github.com/fohrloop/dash-uploader/issues/16)).

Point `configure_upload()` at a mounted persistent volume, or run a single
instance with sticky sessions. Uploading straight to object storage is tracked
in [ROADMAP.md](../ROADMAP.md) under theme 4.

## Multiple worker processes

`gunicorn -w 4` has the same problem for a different reason: chunks are
round-robined across workers, and each worker only sees the chunks it handled
([#53](https://github.com/fohrloop/dash-uploader/issues/53)). Because the chunk
directory is shared on disk, this works if all workers share a filesystem —
which they do on one host, but not across hosts.

If uploads fail intermittently under multiple workers, confirm the workers
share the upload folder before looking anywhere else.
