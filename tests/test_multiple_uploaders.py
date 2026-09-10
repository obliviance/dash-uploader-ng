"""Several du.Upload components in one app (upstream #35, #124, #127, #106, #27).

The largest and longest-running cluster of upstream requests, asked in some
form every year since 2020. Two things blocked it:

1. `decorate_server` registered its routes with `endpoint=None`, so Flask
   derived the endpoint name from the view function -- `get`/`post` for every
   handler instance. A second `configure_upload()` died with "View function
   mapping is overwriting an existing endpoint function: get".
2. Configuration lived in module-level globals, so even if the route had
   registered, the second call would have silently overwritten the first one's
   upload folder.

Configuration now lives in a registry keyed by component id, with a default
entry for apps that only ever call `configure_upload()` once -- which must keep
behaving exactly as before.
"""

import io

import dash
import pytest
from dash.dependencies import Output, State

import dash_uploader_ng as du
from dash_uploader_ng import settings

# `from dash import html` is dash 2.0+ syntax. This package supports dash>=1.1.0
# (see docs/upstream-compatibility.md), and CI runs the suite against dash 1.x,
# where the components live in their own distributions.
if du.utils.dash_version_is_at_least("2.0.0"):
    from dash import html
else:  # pragma: no cover - only on dash 1.x
    import dash_html_components as html


@pytest.fixture(autouse=True)
def clean_registry():
    """The configuration registry is process-global; isolate every test."""
    settings.reset()
    yield
    settings.reset()


def send(app, api, name, content=b"payload", upload_id="sess"):
    form = {
        "flowChunkNumber": "1",
        "flowTotalChunks": "1",
        "flowCurrentChunkSize": str(len(content)),
        "flowFilename": name,
        "flowIdentifier": "9-" + name.replace(".", ""),
        "flowRelativePath": name,
        "upload_id": upload_id,
        "file": (io.BytesIO(content), name),
    }
    return app.server.test_client().post(
        api, data=form, content_type="multipart/form-data"
    )


def files_in(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


class TestTwoUploaders:
    @pytest.fixture
    def app(self, tmp_path):
        agreements = tmp_path / "agreements"
        images = tmp_path / "images"
        agreements.mkdir()
        images.mkdir()

        application = dash.Dash(__name__)
        du.configure_upload(
            application, str(agreements),
            upload_api="/API/agreements", upload_component_ids="agreement-upload",
        )
        du.configure_upload(
            application, str(images),
            upload_api="/API/images", upload_component_ids=["image-upload"],
        )
        application.layout = html.Div(
            [du.Upload(id="agreement-upload"), du.Upload(id="image-upload")]
        )
        application._folders = (agreements, images)
        return application

    def test_a_second_configure_upload_no_longer_raises(self, app):
        # Guarded by the fixture having constructed successfully at all.
        assert len(settings.configurations) == 2

    def test_each_component_posts_to_its_own_endpoint(self, app):
        assert du.Upload(id="agreement-upload").service == "/API/agreements"
        assert du.Upload(id="image-upload").service == "/API/images"

    def test_uploads_land_in_separate_folders(self, app):
        agreements, images = app._folders

        assert send(app, "/API/agreements", "deal.pdf").status_code == 200
        assert send(app, "/API/images", "pic.png").status_code == 200

        assert files_in(agreements) == ["sess/deal.pdf"]
        assert files_in(images) == ["sess/pic.png"]

    def test_same_filename_in_both_uploaders_does_not_collide(self, app):
        """#35 explicitly calls this out: identical filenames must not clash."""
        agreements, images = app._folders

        send(app, "/API/agreements", "data.csv", b"from-agreements")
        send(app, "/API/images", "data.csv", b"from-images")

        assert (agreements / "sess" / "data.csv").read_bytes() == b"from-agreements"
        assert (images / "sess" / "data.csv").read_bytes() == b"from-images"

    def test_callbacks_report_paths_under_the_right_folder(self, app):
        agreements, images = app._folders
        seen = {}

        @du.callback(output=Output("out-a", "children"), id="agreement-upload")
        def _a(status):
            seen["agreement"] = str(status.latest_file)
            return ""

        @du.callback(output=Output("out-b", "children"), id="image-upload")
        def _b(status):
            seen["image"] = str(status.latest_file)
            return ""

        for key in ("agreement-upload", "image-upload"):
            entry = app.callback_map[
                [k for k in app.callback_map if key in str(app.callback_map[k])][0]
            ]

        # Invoke each registered wrapper directly.
        wrappers = [
            v["callback"] for v in app.callback_map.values()
        ]
        for wrapper in wrappers:
            inner = getattr(wrapper, "__wrapped__", wrapper)
            inner(1, ["f.dat"], 1, 1.0, 1.0, "sess")

        assert seen["agreement"] == str(agreements / "sess" / "f.dat")
        assert seen["image"] == str(images / "sess" / "f.dat")


class TestSingleUploaderIsUnaffected:
    """The overwhelmingly common case must behave exactly as it always has."""

    def test_no_component_ids_registers_a_default_used_by_any_id(self, tmp_path):
        app = dash.Dash(__name__)
        du.configure_upload(app, str(tmp_path))

        # Any component id resolves to the default configuration.
        assert du.Upload(id="whatever").service == "/API/dash-uploader"
        assert settings.get_config("whatever").upload_folder_root == str(tmp_path)

    def test_legacy_module_globals_still_mirror_the_default(self, tmp_path):
        app = dash.Dash(__name__)
        du.configure_upload(app, str(tmp_path))

        # Documented, and read by code in the wild.
        assert settings.UPLOAD_FOLDER_ROOT == str(tmp_path)
        assert settings.app is app

    def test_upload_before_configure_still_renders(self):
        """Layouts are often defined at import time, before configuration."""
        component = du.Upload(id="not-configured-yet")
        assert component.service == "/API/dash-uploader"


class TestErrors:
    def test_reusing_an_upload_api_is_reported_clearly(self, tmp_path):
        app = dash.Dash(__name__)
        du.configure_upload(app, str(tmp_path), upload_component_ids="a")

        with pytest.raises(ValueError, match="already registered"):
            du.configure_upload(app, str(tmp_path), upload_component_ids="b")

    def test_callback_before_configure_is_reported_clearly(self):
        with pytest.raises(settings.NotConfigured, match="configure_upload"):

            @du.callback(output=Output("o", "children"), id="nope")
            def _cb(status):  # pragma: no cover
                return ""

    def test_non_string_component_ids_are_rejected(self, tmp_path):
        app = dash.Dash(__name__)
        with pytest.raises(TypeError, match="sequence of strings"):
            du.configure_upload(app, str(tmp_path), upload_component_ids=[123])


class TestFlaskServerAccepted:
    """up#39 also asked for a bare Flask app, for non-Dash hosts."""

    def test_configure_upload_accepts_a_flask_server(self, tmp_path):
        import flask

        server = flask.Flask(__name__)
        du.configure_upload(server, str(tmp_path), upload_api="/API/up")

        content = b"payload"
        form = {
            "flowChunkNumber": "1",
            "flowTotalChunks": "1",
            "flowCurrentChunkSize": str(len(content)),
            "flowFilename": "a.csv",
            "flowIdentifier": "9-acsv",
            "flowRelativePath": "a.csv",
            "upload_id": "sess",
            "file": (io.BytesIO(content), "a.csv"),
        }
        response = server.test_client().post(
            "/API/up", data=form, content_type="multipart/form-data"
        )
        assert response.status_code == 200
        assert files_in(tmp_path) == ["sess/a.csv"]

    def test_callback_on_a_flask_only_config_explains_the_problem(self, tmp_path):
        import flask

        server = flask.Flask(__name__)
        du.configure_upload(server, str(tmp_path), upload_api="/API/up")

        with pytest.raises(TypeError, match="needs a dash.Dash app"):

            @du.callback(output=Output("o", "children"))
            def _cb(status):  # pragma: no cover
                return ""
