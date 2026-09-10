"""Behaviours this fork deliberately keeps identical to upstream dash-uploader.

`test_upstream_parity.py` diffs request/response outcomes against the vendored
upstream handler. This module pins the things that are not visible in a single
request/response pair -- subclass hook ordering, Flask endpoint names, module
globals, dependency floors -- each of which drifted at some point and was
brought back.

Every case here answers the question "would an app written against
dash-uploader still work if it only changed the import?". When one of these
fails, the fork has stopped being a drop-in replacement, which is a bigger deal
than the feature that broke it.
"""

import io
import re
import tempfile

import flask
import pytest

from dash_uploader_ng.configure_upload import decorate_server
from dash_uploader_ng.httprequesthandler import MAX_CHUNKS, HttpRequestHandler
from dash_uploader_ng.safepath import _CHUNK_SUFFIX_BYTES

UPLOAD_API = "/API/dash-uploader"


def build(root, handler=HttpRequestHandler, upload_api=UPLOAD_API, server=None):
    # No dots or slashes in a Flask app name -- see the note in
    # test_upstream_parity.build().
    name = re.sub(r"\W+", "_", f"compat_{id(root)}_{upload_api}")
    server = server or flask.Flask(name)
    server.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    decorate_server(
        server, str(root), upload_api,
        http_request_handler=handler, use_upload_id=True,
    )
    return server


def post(client, api=UPLOAD_API, **over):
    form = {
        "flowChunkNumber": "1", "flowTotalChunks": "1", "flowCurrentChunkSize": "5",
        "flowFilename": "r.csv", "flowIdentifier": "5-rcsv",
        "flowRelativePath": "r.csv", "upload_id": "sess1",
        "file": (io.BytesIO(b"hello"), "r.csv"),
    }
    form.update(over)
    return client.post(api, data=form, content_type="multipart/form-data")


class TestSubclassHooks:
    """`post_after` / `get_after` run on failure, as they did upstream.

    Upstream swallowed a failing `_post` into a `None` return, so the
    `post_after()` line in its documented subclass template still executed
    before Flask turned that None into a 500. Subclasses use these hooks for
    cleanup, audit logging, metrics and lock release; skipping them on the
    error path is exactly when that hurts.
    """

    def _handler(self, calls, fail=False):
        class Recording(HttpRequestHandler):
            def post_before(self):
                calls.append("post_before")

            def post_after(self):
                calls.append("post_after")

            def get_before(self):
                calls.append("get_before")

            def get_after(self):
                calls.append("get_after")

            if fail:
                def _post(self):
                    calls.append("_post")
                    raise RuntimeError("e.g. the disk filled up")

                def _get(self):
                    calls.append("_get")
                    raise RuntimeError("e.g. the disk filled up")

        return Recording

    def test_post_after_runs_when_the_request_fails(self, tmp_path):
        calls = []
        client = build(tmp_path, self._handler(calls, fail=True)).test_client()

        assert post(client).status_code == 500
        assert calls == ["post_before", "_post", "post_after"]

    def test_get_after_runs_when_the_request_fails(self, tmp_path):
        calls = []
        client = build(tmp_path, self._handler(calls, fail=True)).test_client()

        client.get(UPLOAD_API, query_string={
            "flowChunkNumber": "1", "flowTotalChunks": "1",
            "flowFilename": "r.csv", "flowIdentifier": "5-rcsv",
            "upload_id": "sess1",
        })
        assert calls == ["get_before", "_get", "get_after"]

    def test_post_after_still_runs_on_success(self, tmp_path):
        calls = []
        client = build(tmp_path, self._handler(calls)).test_client()

        assert post(client).status_code == 200
        assert calls == ["post_before", "post_after"]

    def test_abort_from_post_before_is_not_swallowed(self, tmp_path):
        """The documented way to reject an unauthorised upload."""
        class Guarded(HttpRequestHandler):
            def post_before(self):
                flask.abort(403, "nope")

        client = build(tmp_path, Guarded).test_client()
        assert post(client).status_code == 403


class TestFlaskEndpointNames:
    """The first uploader keeps upstream's `get` / `post` endpoint names.

    Apps exempt the upload route from CSRF, or look it up in
    `app.view_functions`, by name. Renaming it unconditionally broke that for
    every single-uploader app -- which is every app that could have worked
    upstream at all.
    """

    def test_a_single_uploader_uses_upstreams_names(self, tmp_path):
        server = build(tmp_path)
        registered = {e for e in server.view_functions if "static" not in e}
        assert registered == {"get", "post"}

    def test_the_upload_route_is_reachable_by_endpoint_name(self, tmp_path):
        server = build(tmp_path)
        with server.test_request_context():
            assert flask.url_for("post") == UPLOAD_API
        assert callable(server.view_functions["post"])

    def test_a_second_uploader_gets_its_own_names_instead_of_colliding(self, tmp_path):
        server = build(tmp_path)
        build(tmp_path / "other", upload_api="/API/other", server=server)

        registered = {e for e in server.view_functions if "static" not in e}
        assert {"get", "post"} <= registered
        assert len(registered) == 4, registered

    def test_both_endpoints_still_serve_after_the_second_registration(self, tmp_path):
        (tmp_path / "other").mkdir()
        server = build(tmp_path)
        build(tmp_path / "other", upload_api="/API/other", server=server)
        client = server.test_client()

        assert post(client).status_code == 200
        assert post(client, api="/API/other").status_code == 200


class TestSettingsGlobalsRemainWritable:
    """Assigning to `settings.UPLOAD_FOLDER_ROOT` still redirects reported paths.

    Upstream read that global inside the callback on every fire, which is the
    only workaround anyone has for upstream #17. Freezing it into the
    registered config made the assignment a silent no-op, which is worse than
    not supporting it.
    """

    @pytest.fixture
    def settings(self):
        import dash_uploader_ng.settings as settings

        settings.reset()
        yield settings
        settings.reset()

    def test_the_default_config_follows_the_module_global(self, settings):
        import dash

        from dash_uploader_ng.callbacks import _create_dash_callback

        app = dash.Dash(__name__)
        import dash_uploader_ng as du

        du.configure_upload(app, tempfile.mkdtemp())

        seen = {}
        wrapper = _create_dash_callback(
            lambda status: seen.update(files=[str(f) for f in status.uploaded_files]),
            settings,
            component_id="uploader",
        )

        settings.UPLOAD_FOLDER_ROOT = "/redirected"
        wrapper(1, ["r.csv"], 1, 0.1, 0.1, "sess1")

        assert seen["files"] == ["/redirected/sess1/r.csv"]

    def test_a_named_config_is_not_affected_by_the_global(self, settings):
        import dash

        from dash_uploader_ng.callbacks import _create_dash_callback

        app = dash.Dash(__name__)
        import dash_uploader_ng as du

        own = tempfile.mkdtemp()
        du.configure_upload(app, tempfile.mkdtemp())
        du.configure_upload(
            app, own, upload_api="/API/named", upload_component_ids="named"
        )

        seen = {}
        wrapper = _create_dash_callback(
            lambda status: seen.update(files=[str(f) for f in status.uploaded_files]),
            settings,
            component_id="named",
        )

        settings.UPLOAD_FOLDER_ROOT = "/redirected"
        wrapper(1, ["r.csv"], 1, 0.1, 0.1, "sess1")

        assert seen["files"] == [f"{own}/sess1/r.csv"]


class TestNoArtificialCeilings:
    """Upstream imposed no chunk-count limit; ours must not bite a real upload."""

    @pytest.mark.parametrize("n_chunks", [100_001, 250_000, 1_000_000])
    def test_large_chunk_counts_are_accepted(self, tmp_path, n_chunks):
        client = build(tmp_path).test_client()
        response = post(
            client, flowTotalChunks=str(n_chunks), flowChunkNumber="1"
        )
        assert response.status_code == 200

    def test_the_ceiling_is_far_above_any_real_upload(self):
        # 1 MB is the default chunk size, so this is the smallest file size the
        # ceiling could ever refuse.
        smallest_refused_tb = MAX_CHUNKS * 1024 * 1024 / 1024**4
        assert smallest_refused_tb >= 8, (
            f"MAX_CHUNKS refuses uploads from {smallest_refused_tb:.1f} TB; "
            "that is low enough to hit a real deployment"
        )

    def test_the_filename_budget_reserves_room_for_the_largest_chunk_suffix(self):
        """safepath's reservation must track MAX_CHUNKS, or long names break."""
        longest = f"_part_{MAX_CHUNKS}"
        assert len(longest.encode()) <= _CHUNK_SUFFIX_BYTES


class TestTrafficShapeMatchesUpstream:
    def test_the_component_does_not_test_chunks_by_default(self):
        """Upstream hard-coded flow.js `testChunks` to false.

        With it on, every chunk costs an extra GET to the upload endpoint --
        about a thousand of them for a 1 GB upload. An app behind a WAF, proxy
        or rate limiter tuned for upstream must not start seeing those just
        because it changed the import.
        """
        import dash_uploader_ng as du

        assert du.Upload(id="u").resumable is False
