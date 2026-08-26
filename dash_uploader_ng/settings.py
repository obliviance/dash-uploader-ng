"""Per-uploader configuration.

Upstream kept a single set of module-level globals here, which is why an app
could only ever have one uploader: a second ``du.configure_upload()`` call
silently overwrote the first one's folder and API, and Flask refused the
duplicate route outright. That is the root of the largest cluster of upstream
requests -- #35, #124, #127, #106, #27 and #45.

Configuration now lives in a registry keyed by ``du.Upload`` component id, with
``DEFAULT`` (None) as the key for the unnamed configuration. The module-level
names below are kept as a mirror of that default configuration, because they
are the documented way of reading the upload folder and existing apps read
them.
"""

from dataclasses import dataclass, field
from typing import Any

# The default upload api endpoint
# The du.configure_upload can change this
upload_api = "/API/dash-uploader"

# Needed if using a proxy; when dash.Dash is used
# with a `requests_pathname_prefix`.
# The front-end will prefix this string to the requests
# that are made to the proxy server
requests_pathname_prefix = "/"

# From dash source code:
# Note that `requests_pathname_prefix` is the prefix for the AJAX calls that
# originate from the client (the web browser) and `routes_pathname_prefix` is
# the prefix for the API routes on the backend (this flask server).
# `url_base_pathname` will set `requests_pathname_prefix` and
# `routes_pathname_prefix` to the same value.
# If you need these to be different values then you should set
# `requests_pathname_prefix` and `routes_pathname_prefix`,
# not `url_base_pathname`.
routes_pathname_prefix = "/"

#: Key for the configuration that applies to any component not given one of
#: its own.
DEFAULT = None


class NotConfigured(Exception):
    """Raised when a component or callback is used before configure_upload."""


@dataclass
class UploadConfig:
    """Everything one ``du.configure_upload()`` call established."""

    app: Any
    upload_folder_root: str
    upload_api: str
    use_upload_id: bool = True
    requests_pathname_prefix: str = "/"
    routes_pathname_prefix: str = "/"
    #: Component ids this configuration was registered for; empty for the
    #: default configuration.
    component_ids: tuple = field(default_factory=tuple)

    @property
    def service(self):
        """The URL the browser posts to, including any proxy prefix."""
        from dash_uploader_ng.upload import update_upload_api

        return update_upload_api(self.requests_pathname_prefix, self.upload_api)


#: component id (or DEFAULT) -> UploadConfig
configurations = {}


def register(config):
    """Store ``config`` under each of its component ids, or as the default."""
    keys = config.component_ids or (DEFAULT,)
    for key in keys:
        configurations[key] = config

    if DEFAULT in keys:
        _mirror_to_module_globals(config)


def get_config(component_id=DEFAULT):
    """Return the configuration governing ``component_id``.

    Falls back to the default configuration, so an app that calls
    ``configure_upload()`` once behaves exactly as it always has, regardless of
    what its components are called.
    """
    config = configurations.get(component_id)
    if config is not None:
        return config
    config = configurations.get(DEFAULT)
    if config is not None:
        return config
    raise NotConfigured(
        "du.configure_upload must be called before du.Upload or du.callback. "
        f"Nothing is registered for component id {component_id!r}, and there "
        "is no default configuration."
    )


def has_config(component_id=DEFAULT):
    return component_id in configurations or DEFAULT in configurations


def reset():
    """Forget every registered configuration.

    Only intended for tests: the registry is process-global, so tests that
    configure apps would otherwise leak into one another.
    """
    global upload_api, requests_pathname_prefix, routes_pathname_prefix

    configurations.clear()
    upload_api = "/API/dash-uploader"
    requests_pathname_prefix = "/"
    routes_pathname_prefix = "/"
    for name in ("app", "UPLOAD_FOLDER_ROOT"):
        globals().pop(name, None)


def _mirror_to_module_globals(config):
    """Keep the legacy module-level names pointing at the default config.

    ``settings.UPLOAD_FOLDER_ROOT`` and ``settings.app`` are the documented way
    to read where uploads land, and code in the wild uses them.
    """
    global app, UPLOAD_FOLDER_ROOT, upload_api
    global requests_pathname_prefix, routes_pathname_prefix

    app = config.app
    UPLOAD_FOLDER_ROOT = config.upload_folder_root
    upload_api = config.upload_api
    requests_pathname_prefix = config.requests_pathname_prefix
    routes_pathname_prefix = config.routes_pathname_prefix
