import logging

import dash_uploader_ng.settings as settings
from dash_uploader_ng.upload import update_upload_api
from dash_uploader_ng.httprequesthandler import HttpRequestHandler
from dash_uploader_ng.settings import UploadConfig


logger = logging.getLogger("dash_uploader_ng")


def _as_component_ids(upload_component_ids):
    """Normalise the `upload_component_ids` argument to a tuple of ids."""
    if upload_component_ids is None:
        return ()
    if isinstance(upload_component_ids, str):
        return (upload_component_ids,)
    ids = tuple(upload_component_ids)
    for component_id in ids:
        if not isinstance(component_id, str):
            raise TypeError(
                "upload_component_ids must be a string or a sequence of "
                f"strings, got {type(component_id).__name__}"
            )
    return ids


def _endpoint_name(upload_api):
    """A Flask endpoint name unique to this upload API path.

    Upstream passed `None`, letting Flask derive the endpoint from the view
    function's name -- which is `get`/`post` for every handler instance. A
    second `configure_upload()` therefore died with "View function mapping is
    overwriting an existing endpoint function: get", the immediate cause of
    upstream #27, #124 and #127.
    """
    slug = "".join(c if c.isalnum() else "_" for c in upload_api).strip("_")
    return f"dash_uploader_ng_{slug}"


def configure_upload(
    app,
    folder,
    use_upload_id=True,
    upload_api=None,
    http_request_handler=None,
    upload_component_ids=None,
):
    r"""
    Configure the upload APIs for dash app.
    This function is required to be called before using du.callback.

    May be called more than once, to serve several upload components writing to
    different destinations. Each call after the first needs its own
    `upload_api` (they become distinct Flask routes) and its own
    `upload_component_ids` (so components know which one governs them).

    Parameters
    ---------
    app: dash.Dash or flask.Flask
        The application instance. A bare Flask server is accepted for apps not
        built on Dash's own app object; `du.callback` still needs a Dash app.
    folder: str
        The folder where to upload files.
        Can be relative ("uploads") or
        absolute (r"C:\tmp\my_uploads").
        If the folder does not exist, it will
        be created automatically.
    use_upload_id: bool
        Determines if the uploads are put into
        folders defined by a "upload id" (upload_id).
        If True, uploads will be put into `folder`/<upload_id>/;
        that is, every user (for example with different
        session id) will use their own folder. If False,
        all files from all sessions are uploaded into
        same folder (not recommended).
    upload_api: None or str
        The upload api endpoint to use; the url that is used
        internally for the upload component POST and GET HTTP
        requests. For example: "/API/dash-uploader"
    http_request_handler: None or class
        Used for custom configuration on the Http POST and GET requests.
        This can be used to add validation for the HTTP requests (Important
        if your site is public!). If None, dash_uploader_ng.HttpRequestHandler
        is used. If you provide a class, use a subclass of HttpRequestHandler.
        See the documentation of dash_uploader_ng.HttpRequestHandler for
        more details.
    upload_component_ids: None, str, or sequence of str
        Which `du.Upload` components this configuration governs.

        None (the default) registers it as the *default* configuration, used by
        any component that has no configuration of its own. A single-uploader
        app should leave this alone.

        Name the components explicitly when one app has several uploaders that
        must write to different folders::

            du.configure_upload(app, "/data/agreements",
                                upload_api="/API/agreements",
                                upload_component_ids="agreement-upload")
            du.configure_upload(app, "/data/images",
                                upload_api="/API/images",
                                upload_component_ids=["image-upload"])
    """
    component_ids = _as_component_ids(upload_component_ids)

    if upload_api is None:
        upload_api = settings.upload_api

    server = app.server if hasattr(app, "server") else app

    # Needed if using a proxy. A bare Flask server has no Dash config, in which
    # case there are no prefixes to honour.
    app_config = getattr(app, "config", None)
    if app_config is not None and hasattr(app_config, "get"):
        requests_pathname_prefix = (
            app_config.get("requests_pathname_prefix", "/") or "/"
        )
        routes_pathname_prefix = app_config.get("routes_pathname_prefix", "/") or "/"
    else:
        requests_pathname_prefix = routes_pathname_prefix = "/"

    config = UploadConfig(
        app=app,
        upload_folder_root=folder,
        upload_api=upload_api,
        use_upload_id=use_upload_id,
        requests_pathname_prefix=requests_pathname_prefix,
        routes_pathname_prefix=routes_pathname_prefix,
        component_ids=component_ids,
    )
    settings.register(config)

    if http_request_handler is None:
        http_request_handler = HttpRequestHandler

    decorate_server(
        server,
        folder,
        update_upload_api(routes_pathname_prefix, upload_api),
        http_request_handler=http_request_handler,
        use_upload_id=use_upload_id,
    )


def decorate_server(
    server,
    temp_base,
    upload_api,
    http_request_handler,
    use_upload_id=True,
):
    """
    Parameters
    ----------
    server: flask.Flask
        The flask server instance
    temp_base: str
        The upload root folder
    upload_api: str
        The upload api endpoint to use; the url that is used
        internally for the upload component POST and GET HTTP
        requests.
    use_upload_id: bool
        Determines if the uploads are put into
        folders defined by a "upload id" (upload_id).
        If True, uploads will be put into `folder`/<upload_id>/;
        that is, every user (for example with different
        session id) will use their own folder. If False,
        all files from all sessions are uploaded into
        same folder (not recommended).
    """

    handler = http_request_handler(
        server, upload_folder=temp_base, use_upload_id=use_upload_id
    )

    # Registering the same upload_api twice is a mistake worth naming plainly:
    # otherwise Flask raises "View function mapping is overwriting an existing
    # endpoint function", which does not point at the actual problem.
    if any(rule.rule == upload_api for rule in server.url_map.iter_rules()):
        raise ValueError(
            f"The upload API {upload_api!r} is already registered on this "
            "server. Give each du.configure_upload() call its own `upload_api` "
            "when configuring more than one uploader."
        )

    endpoint = _endpoint_name(upload_api)
    server.add_url_rule(upload_api, f"{endpoint}_get", handler.get, methods=["GET"])
    server.add_url_rule(upload_api, f"{endpoint}_post", handler.post, methods=["POST"])
