"""Tests for extra callback state and multiple outputs.

Covers upstream #104 ("passing additional input to callback", 6 comments) and
#13 ("multiple output", 10 comments), and supersedes the never-merged upstream
PR #130.

`du.callback` was a closed box: exactly one output, no extra values. The
canonical blocked use case is a dropdown that chooses which directory the
finished upload should be filed under — the callback fires, but has no way to
read the dropdown.

These run headless against a real Dash app: the callback is registered for
real, then invoked through Dash's own dispatch machinery so the argument order
is genuinely exercised rather than assumed.
"""

import dash
import pytest
from dash.dependencies import Output, State

import dash_uploader_ng as du
from dash_uploader_ng.callbacks import _normalize_state

# `from dash import html` is dash 2.0+ syntax. This package supports dash>=1.1.0
# (see docs/upstream-compatibility.md), and CI runs the suite against dash 1.x,
# where the components live in their own distributions.
if du.utils.dash_version_is_at_least("2.0.0"):
    from dash import html
else:  # pragma: no cover - only on dash 1.x
    import dash_html_components as html


@pytest.fixture
def app(tmp_path):
    application = dash.Dash(__name__)
    du.configure_upload(application, str(tmp_path))
    return application


def registered_callback(application):
    """The most recently registered callback's function and its dependencies."""
    key = list(application.callback_map)[-1]
    entry = application.callback_map[key]
    return entry["callback"], entry["inputs"], entry.get("state", [])


def call(application, *values):
    """Invoke the registered callback the way Dash's dispatcher would."""
    func, _, _ = registered_callback(application)
    # Dash wraps the user function; `__wrapped__` is the wrapper we registered.
    inner = getattr(func, "__wrapped__", func)
    return inner(*values)


class TestNormalizeState:
    def test_none_means_no_extra_state(self):
        assert _normalize_state(None) == []

    def test_a_bare_state_is_wrapped(self):
        s = State("x", "value")
        assert _normalize_state(s) == [s]

    def test_a_sequence_is_preserved_in_order(self):
        a, b = State("a", "value"), State("b", "value")
        assert _normalize_state([a, b]) == [a, b]
        assert _normalize_state((a, b)) == [a, b]

    def test_an_output_is_rejected_with_a_useful_message(self):
        with pytest.raises(TypeError, match="State"):
            _normalize_state([Output("a", "children")])

    def test_an_input_is_rejected_and_says_why(self):
        from dash.dependencies import Input

        with pytest.raises(TypeError, match="Input is not supported"):
            _normalize_state([Input("a", "value")])

    def test_a_non_sequence_is_rejected(self):
        with pytest.raises(TypeError):
            _normalize_state(42)


class TestExtraState:
    def test_state_is_registered_after_the_builtin_state(self, app):
        @du.callback(
            output=Output("out", "children"),
            id="uploader",
            state=[State("folder", "value"), State("user", "value")],
        )
        def _cb(status, folder, user):  # pragma: no cover - registration only
            return ""

        _, _, states = registered_callback(app)
        # Dash stores registered dependencies as plain dicts, not State objects.
        ids = [s["id"] for s in states]
        # Five builtin States on the uploader itself, then the user's, in order.
        assert ids[:5] == ["uploader"] * 5
        assert ids[5:] == ["folder", "user"]

    def test_extra_values_reach_the_callback_in_order(self, app, tmp_path):
        received = {}

        @du.callback(
            output=Output("out", "children"),
            id="uploader",
            state=[State("folder", "value"), State("user", "value")],
        )
        def _cb(status, folder, user):
            received["folder"] = folder
            received["user"] = user
            received["file"] = status.latest_file.name
            return "ok"

        result = call(
            app,
            1,                    # dashAppCallbackBump
            ["report.csv"],       # uploadedFileNames
            1,                    # totalFilesCount
            1.0,                  # uploadedFilesSize
            1.0,                  # totalFilesSize
            "session-1",          # upload_id
            "/data/archive",      # State: folder
            "awwab",              # State: user
        )

        assert result == "ok"
        assert received == {
            "folder": "/data/archive",
            "user": "awwab",
            "file": "report.csv",
        }

    def test_a_single_state_need_not_be_wrapped_in_a_list(self, app):
        seen = {}

        @du.callback(
            output=Output("out", "children"),
            id="uploader",
            state=State("folder", "value"),
        )
        def _cb(status, folder):
            seen["folder"] = folder
            return "ok"

        call(app, 1, ["a.csv"], 1, 1.0, 1.0, "s", "/data")
        assert seen["folder"] == "/data"

    def test_omitting_state_keeps_the_original_signature(self, app):
        """The existing one-argument form must keep working unchanged."""
        seen = {}

        @du.callback(output=Output("out", "children"), id="uploader")
        def _cb(status):
            seen["n"] = status.n_uploaded
            return "ok"

        assert call(app, 1, ["a.csv", "b.csv"], 2, 2.0, 2.0, "s") == "ok"
        assert seen["n"] == 2


class TestMultipleOutputs:
    def test_a_list_of_outputs_is_registered(self, app):
        @du.callback(
            output=[Output("a", "children"), Output("b", "children")],
            id="uploader",
        )
        def _cb(status):  # pragma: no cover - registration only
            return "x", "y"

        key = list(app.callback_map)[-1]
        # Dash encodes multiple outputs as a single "..a.children...b.children.." key
        assert "a.children" in key and "b.children" in key

    def test_a_tuple_return_reaches_dash_intact(self, app):
        @du.callback(
            output=[Output("a", "children"), Output("b", "children")],
            id="uploader",
        )
        def _cb(status):
            return f"{status.n_uploaded} files", status.upload_id

        assert call(app, 1, ["a.csv"], 1, 1.0, 1.0, "sess") == ("1 files", "sess")

    def test_outputs_and_state_compose(self, app):
        @du.callback(
            output=[Output("a", "children"), Output("b", "children")],
            id="uploader",
            state=[State("folder", "value")],
        )
        def _cb(status, folder):
            return status.latest_file.name, folder

        assert call(app, 1, ["r.csv"], 1, 1.0, 1.0, "s", "/data") == ("r.csv", "/data")


class TestUnchangedBehaviour:
    def test_no_upload_yet_still_prevents_the_update(self, app):
        from dash.exceptions import PreventUpdate

        @du.callback(output=Output("out", "children"), id="uploader")
        def _cb(status):  # pragma: no cover - should not be reached
            return "should not run"

        with pytest.raises(PreventUpdate):
            call(app, 0, None, 0, 0.0, 0.0, "s")

    def test_extra_state_does_not_change_the_upload_paths(self, app, tmp_path):
        seen = {}

        @du.callback(
            output=Output("out", "children"),
            id="uploader",
            state=[State("folder", "value")],
        )
        def _cb(status, folder):
            seen["paths"] = [str(p) for p in status.uploaded_files]
            return "ok"

        call(app, 1, ["a.csv"], 1, 1.0, 1.0, "sess-9", "/ignored")
        assert seen["paths"] == [str(tmp_path / "sess-9" / "a.csv")]
