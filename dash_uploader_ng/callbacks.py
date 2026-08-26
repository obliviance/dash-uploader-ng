from pathlib import Path

from dash.exceptions import PreventUpdate
from dash.dependencies import Input, State

import dash_uploader_ng.settings as settings
from dash_uploader_ng.uploadstatus import UploadStatus
from dash_uploader_ng.utils import dash_version_is_at_least


def _normalize_state(state):
    """Return the user's `state=` argument as a list of dash State objects.

    Accepts None, a single State, or any sequence of them, so that the common
    single-value case does not have to be wrapped in a list.

    Raises
    ------
    TypeError
        If something that is not a State is passed. Without this the failure
        surfaces much later as an opaque error from inside Dash's own callback
        registration, which is hard to trace back to this argument.
    """
    if state is None:
        return []
    if isinstance(state, State):
        return [state]
    try:
        states = list(state)
    except TypeError:
        raise TypeError(
            f"du.callback(state=...) expects a dash State or a sequence of "
            f"them, got {type(state).__name__}"
        ) from None
    for item in states:
        if not isinstance(item, State):
            raise TypeError(
                f"du.callback(state=...) expects dash State objects, got "
                f"{type(item).__name__}. Note that Input is not supported here: "
                f"the upload completing is the only thing that may fire this "
                f"callback."
            )
    return states


def _create_dash_callback(callback, settings, component_id=None):  # pylint: disable=redefined-outer-name
    """Wrap the dash callback with the du.settings.
    This function could be used as a wrapper. It will add the
    configurations of dash-uploader to the callback.

    Any extra States the user registered arrive after the six fixed arguments,
    in the order they were given, and are passed straight through to the
    user's function after the UploadStatus.
    """

    def wrapper(
        callbackbump,
        uploaded_filenames,
        total_files_count,
        uploaded_files_size,
        total_files_size,
        upload_id,
        *extra_state_values,
    ):
        if not callbackbump:
            raise PreventUpdate()

        uploadedfilepaths = []
        if uploaded_filenames is not None:
            # Resolve the folder for *this* component, so a second uploader
            # reports paths under its own destination (upstream #124, #127).
            upload_folder_root = settings.get_config(component_id).upload_folder_root
            if upload_id:
                root_folder = Path(upload_folder_root) / upload_id
            else:
                root_folder = Path(upload_folder_root)

            for filename in uploaded_filenames:
                file = root_folder / filename
                uploadedfilepaths.append(str(file))

        status = UploadStatus(
            uploaded_files=uploadedfilepaths,
            n_total=total_files_count,
            uploaded_size_mb=uploaded_files_size,
            total_size_mb=total_files_size,
            upload_id=upload_id,
        )
        return callback(status, *extra_state_values)

    return wrapper


def callback(
    output,
    id="dash-uploader",
    state=None,
):
    """
    Add a callback to dash application.
    This callback fires when upload is completed.
    Note: Must be called after du.configure_upload!

    Parameters
    ----------
    output: dash Output, or a list of them
        The output dash component(s). A list updates several outputs from one
        upload, in which case the decorated function returns a tuple.
    id: str
        The id of the du.Upload component.
    state: dash State, a sequence of them, or None
        Extra values to pass to the callback alongside the UploadStatus, in the
        order given. Use this to read other parts of your layout at the moment
        the upload finishes -- which directory to file it under, the logged-in
        user, a CSRF token.

        Input is deliberately not accepted: the upload completing is the only
        thing that may fire this callback, and an extra Input would let
        unrelated interactions re-trigger it with stale upload data.

    Example
    -------
    @du.callback(
       output=Output('callback-output', 'children'),
       id='dash-uploader',
    )
    def get_a_list(status):
        return html.Ul([html.Li(str(x)) for x in status.uploaded_files])

    With extra state and several outputs:

    @du.callback(
        output=[Output('out', 'children'), Output('log', 'children')],
        id='dash-uploader',
        state=[State('target-folder', 'value')],
    )
    def on_completion(status, target_folder):
        shutil.move(status.latest_file, target_folder)
        return f"Filed under {target_folder}", f"{status.n_uploaded} file(s)"
    """
    extra_states = _normalize_state(state)

    def add_callback(function):
        """
        Parameters
        ---------
        function: callable
            Function that receivers one argument,
            filenames and returns one argument,
            a dash component. The filenames is either
            None or list of str containing the uploaded
            file(s).
        output: dash.dependencies.Output
            The dash output. For example:
            Output('callback-output', 'children')

        """
        dash_callback = _create_dash_callback(
            function,
            settings,
            component_id=id,
        )

        if not settings.has_config(id):
            raise settings.NotConfigured(
                "du.configure_upload must be called before @du.callback can be "
                f"used. Nothing is registered for component id {id!r}, and "
                "there is no default configuration."
            )

        config = settings.get_config(id)
        app = config.app
        if not hasattr(app, "callback"):
            raise TypeError(
                "@du.callback needs a dash.Dash app, but du.configure_upload "
                f"was given a {type(app).__name__}. Configure with the Dash "
                "app (or its .server for the routes only) if you need "
                "callbacks."
            )

        kwargs = dict()
        if dash_version_is_at_least("1.12"):
            # See: https://github.com/plotly/dash/blob/dev/CHANGELOG.md  and
            #      https://community.plotly.com/t/dash-v1-12-0-release-pattern-matching-callbacks-fixes-shape-drawing-new-datatable-conditional-formatting-options-prevent-initial-call-and-more/38867
            # the `prevent_initial_call` option was added in Dash v.1.12
            kwargs["prevent_initial_call"] = True

        # Input: Change in the props will trigger callback.
        #     Whenever 'this.props.setProps' is called on the JS side,
        #     (dash specific special prop that is passed to every
        #     component of the dash app), a HTTP request is used to
        #     trigger a change in the property/attribute of a dash
        #     python component.
        # State: Pass along extra values without firing the callbacks.
        #
        # See also: https://dash.plotly.com/basic-callbacks
        dash_callback = app.callback(
            output,
            [Input(id, "dashAppCallbackBump")],
            [
                State(id, "uploadedFileNames"),
                State(id, "totalFilesCount"),
                State(id, "uploadedFilesSize"),
                State(id, "totalFilesSize"),
                State(id, "upload_id"),
                # The user's extra States come last, so the wrapper's six fixed
                # positional arguments keep their meaning and the extras land
                # in *extra_state_values in the order they were given.
                *extra_states,
            ],
            **kwargs
        )(dash_callback)

        return function

    return add_callback
