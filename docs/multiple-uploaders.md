# Several uploaders in one app

An app can have more than one `du.Upload`, each writing to its own folder.

```python
import dash
from dash import html
import dash_uploader_ng as du

app = dash.Dash(__name__)

du.configure_upload(
    app, "/data/agreements",
    upload_api="/API/agreements",
    upload_component_ids="agreement-upload",
)
du.configure_upload(
    app, "/data/images",
    upload_api="/API/images",
    upload_component_ids=["image-upload"],
)

app.layout = html.Div([
    du.Upload(id="agreement-upload"),
    du.Upload(id="image-upload"),
])
```

Each call after the first needs:

- **its own `upload_api`** — these become distinct Flask routes;
- **its own `upload_component_ids`** — so components know which configuration
  governs them.

Uploads with the same filename in different uploaders do not collide: each
lands under its own configured folder.

## Single-uploader apps need no changes

Calling `configure_upload()` once, without `upload_component_ids`, registers a
**default** configuration used by any component that has none of its own —
whatever it is called. This is the common case and behaves exactly as it always
has.

```python
du.configure_upload(app, "/data/uploads")
app.layout = html.Div([du.Upload(id="anything-you-like")])
```

## Why it did not work before

Two separate problems, both fixed
([#35](https://github.com/fohrloop/dash-uploader/issues/35),
[#124](https://github.com/fohrloop/dash-uploader/issues/124),
[#127](https://github.com/fohrloop/dash-uploader/issues/127),
[#106](https://github.com/fohrloop/dash-uploader/issues/106),
[#27](https://github.com/fohrloop/dash-uploader/issues/27)):

1. **Colliding Flask endpoints.** The routes were registered with
   `endpoint=None`, so Flask derived the name from the view function — `get`
   and `post` for *every* handler instance. A second `configure_upload()` died
   with `View function mapping is overwriting an existing endpoint function:
   get`. Endpoint names are now derived from the upload API path.
2. **One global configuration.** Even once the route registered, the second
   call overwrote the first one's upload folder, because configuration lived in
   module-level globals. It now lives in a registry keyed by component id.

## Callbacks

Each uploader gets its own callback, and each reports paths under its own
folder:

```python
@du.callback(output=Output("agreement-status", "children"), id="agreement-upload")
def on_agreement(status):
    return f"Filed {status.latest_file.name}"


@du.callback(output=Output("image-status", "children"), id="image-upload")
def on_image(status):
    return f"Stored {status.n_uploaded} image(s)"
```

## Using a bare Flask server

`configure_upload()` accepts a `flask.Flask` instance for apps not built on
Dash's app object — the other half of upstream
[PR #39](https://github.com/fohrloop/dash-uploader/pull/39):

```python
server = flask.Flask(__name__)
du.configure_upload(server, "/data/uploads", upload_api="/API/upload")
```

The upload routes work. `du.callback` does not — it needs a Dash app to
register against, and raises a `TypeError` saying so rather than failing
obscurely later.

## Reading the configuration

```python
from dash_uploader_ng import settings

settings.get_config("image-upload").upload_folder_root   # '/data/images'
settings.get_config("image-upload").service              # '/API/images'
```

`settings.UPLOAD_FOLDER_ROOT` and `settings.app` still exist and mirror the
**default** configuration, so existing code that reads them keeps working.

## Not yet supported

Changing an uploader's destination folder *after* the app is serving
([#17](https://github.com/fohrloop/dash-uploader/issues/17)). The folder is
fixed when `configure_upload()` is called; making it per-request is tracked in
[ROADMAP.md](../ROADMAP.md) alongside the storage-backend work.
