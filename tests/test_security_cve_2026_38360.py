"""End-to-end regression tests for CVE-2026-38360.

Upstream dash-uploader (all versions 0.1.0 through 0.7.0a2, archived without a
patch) joined three attacker-controlled form fields straight onto the upload
root. The published proof of concept is a single unauthenticated POST to
``/API/dash-uploader`` carrying::

    upload_id=../../../../usr/local/lib/python3.10/site-packages

which drops an attacker-chosen file into site-packages -- a ``.pth`` there runs
on the next interpreter start, so this is remote code execution, not merely an
arbitrary write.

test_safepath.py covers the validation helpers in isolation. What these tests
add is proof that the helpers are actually *reached* on the real request path:
they fire complete multipart requests at a live Flask app wired up exactly the
way ``du.configure_upload`` wires one, and then assert against the filesystem
that nothing landed outside the upload root.
"""

import io

import flask
import pytest

from dash_uploader_ng.configure_upload import decorate_server
from dash_uploader_ng.httprequesthandler import HttpRequestHandler

UPLOAD_API = "/API/dash-uploader"

# What a well-behaved flow.js client sends. Individual tests override single
# fields to make each one hostile in exactly one way.
GOOD_UPLOAD_ID = "3e2f1c5a9c4b4e1a9a5e6c1f2b3d4e5f"
GOOD_IDENTIFIER = "11-reportcsv"
GOOD_FILENAME = "report.csv"


@pytest.fixture
def upload_root(tmp_path):
    """The directory the app is configured to write into."""
    root = tmp_path / "uploads"
    root.mkdir()
    return root


@pytest.fixture
def outside_marker(tmp_path):
    """A path outside the upload root that a successful exploit would reach."""
    return tmp_path / "site-packages"


@pytest.fixture
def client(upload_root):
    server = flask.Flask(__name__)
    server.config.update(TESTING=True)
    decorate_server(
        server,
        str(upload_root),
        UPLOAD_API,
        http_request_handler=HttpRequestHandler,
        use_upload_id=True,
    )
    return server.test_client()


def upload(client, content=b"a,b\n1,2\n", *, chunk=1, chunks=1, **overrides):
    """Fire one chunk upload, with `overrides` replacing individual form fields."""
    form = {
        "flowChunkNumber": str(chunk),
        "flowTotalChunks": str(chunks),
        "flowFilename": GOOD_FILENAME,
        "flowIdentifier": GOOD_IDENTIFIER,
        "flowRelativePath": GOOD_FILENAME,
        "upload_id": GOOD_UPLOAD_ID,
    }
    form.update(overrides)
    form["file"] = (io.BytesIO(content), form["flowFilename"])
    return client.post(UPLOAD_API, data=form, content_type="multipart/form-data")


def files_under(path):
    return sorted(p for p in path.rglob("*") if p.is_file())


class TestTheExploit:
    """The published proof of concept, and close variants of it."""

    def test_the_published_poc_is_rejected(self, client, upload_root, tmp_path):
        response = upload(
            client,
            content=b"import os; os.system('id')\n",
            upload_id="../../../../usr/local/lib/python3.10/site-packages",
            flowFilename="evil.pth",
        )

        assert response.status_code == 400
        # Nothing anywhere in the tree outside the upload root.
        assert files_under(tmp_path) == []

    def test_traversal_via_upload_id_writes_nothing_outside_the_root(
        self, client, upload_root, outside_marker
    ):
        response = upload(client, upload_id="../site-packages")

        assert response.status_code == 400
        assert not outside_marker.exists()
        assert files_under(upload_root) == []

    def test_traversal_via_filename_writes_nothing_outside_the_root(
        self, client, upload_root, outside_marker
    ):
        # A directory prefix in flowFilename is legitimate (dropped folders),
        # so this one is flattened rather than refused -- but the file must
        # land inside the upload root either way.
        response = upload(client, flowFilename="../../site-packages/evil.pth")

        assert response.status_code == 200
        assert not outside_marker.exists()
        written = files_under(upload_root)
        assert len(written) == 1
        assert written[0].name == "evil.pth"
        assert written[0].parent == upload_root / GOOD_UPLOAD_ID

    def test_windows_style_traversal_is_handled_on_every_platform(
        self, client, upload_root, tmp_path
    ):
        # Backslash is an ordinary filename character on Linux, so this is
        # inert here -- but the same request against a Windows deployment is
        # traversal, and uploads accepted on one host get served from another.
        response = upload(client, upload_id="..\\..\\..\\windows")

        assert response.status_code == 400
        assert files_under(tmp_path) == []

    def test_traversal_via_identifier_writes_nothing_outside_the_root(
        self, client, upload_root, outside_marker
    ):
        response = upload(client, flowIdentifier="../../site-packages")

        assert response.status_code == 400
        assert not outside_marker.exists()
        assert files_under(upload_root) == []

    def test_absolute_upload_id_is_rejected(self, client, upload_root, tmp_path):
        response = upload(client, upload_id="/etc/cron.d")

        assert response.status_code == 400
        assert files_under(tmp_path) == []

    @pytest.mark.parametrize(
        "field,value",
        [
            ("upload_id", ".."),
            ("upload_id", "."),
            ("upload_id", ".hidden"),
            ("flowIdentifier", ".."),
            ("flowFilename", ".."),
            ("flowFilename", ".bashrc"),
            ("flowFilename", ""),
        ],
    )
    def test_hostile_field_values_are_refused(
        self, client, upload_root, tmp_path, field, value
    ):
        response = upload(client, **{field: value})

        assert response.status_code == 400
        assert files_under(tmp_path) == []

    def test_relative_path_is_flattened_like_the_filename(self, client, upload_root):
        # flowRelativePath is not used to build a path by this handler, but
        # HttpRequestHandler subclasses can read it -- so it gets the same
        # flatten-don't-refuse treatment as flowFilename rather than being
        # passed through raw for a subclass to trip over.
        response = upload(client, flowRelativePath="../../../evil.pth")

        assert response.status_code == 200
        assert files_under(upload_root) == [
            upload_root / GOOD_UPLOAD_ID / GOOD_FILENAME
        ]


class TestMalformedRequests:
    """Fields that reach the filesystem indirectly, or crashed upstream."""

    def test_missing_chunk_count_is_a_400_not_a_500(self, client):
        # Upstream left flowTotalChunks as None and hit a TypeError inside
        # range() further down, which surfaced as a server error.
        response = upload(client, flowTotalChunks="")
        assert response.status_code == 400

    def test_absurd_chunk_count_is_refused(self, client):
        # Unbounded, this allocates one path per claimed chunk on an
        # unauthenticated request.
        response = upload(client, flowTotalChunks="100000000")
        assert response.status_code == 400

    def test_chunk_number_outside_the_declared_range_is_refused(self, client):
        response = upload(client, chunk=5, chunks=2)
        assert response.status_code == 400

    def test_missing_file_part_is_a_400(self, client):
        response = client.post(
            UPLOAD_API,
            data={
                "flowChunkNumber": "1",
                "flowTotalChunks": "1",
                "flowFilename": GOOD_FILENAME,
                "flowIdentifier": GOOD_IDENTIFIER,
                "upload_id": GOOD_UPLOAD_ID,
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 400


class TestUploadsStillWork:
    """The fix must not cost the feature. These are the regression half."""

    def test_a_single_chunk_upload_lands_in_the_right_place(
        self, client, upload_root
    ):
        response = upload(client, content=b"a,b\n1,2\n")

        assert response.status_code == 200
        assert response.get_data(as_text=True) == GOOD_FILENAME

        target = upload_root / GOOD_UPLOAD_ID / GOOD_FILENAME
        assert target.read_bytes() == b"a,b\n1,2\n"
        # The per-upload temp directory is cleaned up on completion.
        assert files_under(upload_root) == [target]

    def test_a_multi_chunk_upload_is_reassembled_in_order(self, client, upload_root):
        assert upload(client, b"first-", chunk=1, chunks=3).status_code == 200
        assert upload(client, b"second-", chunk=2, chunks=3).status_code == 200
        assert upload(client, b"third", chunk=3, chunks=3).status_code == 200

        target = upload_root / GOOD_UPLOAD_ID / GOOD_FILENAME
        assert target.read_bytes() == b"first-second-third"
        assert files_under(upload_root) == [target]

    def test_a_folder_relative_path_is_flattened_not_refused(
        self, client, upload_root
    ):
        # flow.js sends a relative path here when the user drags in a folder;
        # upstream documented that subdirectories are not recreated.
        response = upload(client, flowFilename="nested/dir/report.csv")

        assert response.status_code == 200
        assert (upload_root / GOOD_UPLOAD_ID / "report.csv").exists()

    @pytest.mark.parametrize(
        "filename", ["données.csv", "отчет.csv", "報告書.xlsx", "a-b_c.1.tar.gz"]
    )
    def test_real_world_filenames_survive_intact(
        self, client, upload_root, filename
    ):
        # The reason this fork does not sanitise with
        # werkzeug.utils.secure_filename: it ASCII-folds, so it would mangle
        # the first three of these and empty out a fully non-Latin name.
        response = upload(client, flowFilename=filename, flowIdentifier="12-x")

        assert response.status_code == 200
        assert (upload_root / GOOD_UPLOAD_ID / filename).exists()

    def test_uploading_the_same_file_twice_overwrites_cleanly(
        self, client, upload_root
    ):
        assert upload(client, b"first version").status_code == 200
        assert upload(client, b"second version").status_code == 200

        target = upload_root / GOOD_UPLOAD_ID / GOOD_FILENAME
        assert target.read_bytes() == b"second version"


class TestWithoutUploadId:
    """use_upload_id=False puts every session in one shared folder."""

    @pytest.fixture
    def client(self, upload_root):
        server = flask.Flask(__name__)
        server.config.update(TESTING=True)
        decorate_server(
            server,
            str(upload_root),
            UPLOAD_API,
            http_request_handler=HttpRequestHandler,
            use_upload_id=False,
        )
        return server.test_client()

    def test_upload_lands_directly_in_the_root(self, client, upload_root):
        assert upload(client, b"payload").status_code == 200
        assert (upload_root / GOOD_FILENAME).read_bytes() == b"payload"

    def test_upload_id_is_ignored_rather_than_honoured(
        self, client, upload_root, tmp_path
    ):
        # The upload_id is still validated even though it is not used to build
        # a path here -- rejecting early is cheaper than reasoning about which
        # configurations happen to be safe.
        response = upload(client, upload_id="../../escape")

        assert response.status_code == 400
        assert files_under(tmp_path) == []
