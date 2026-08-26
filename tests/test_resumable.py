"""Tests for resumable uploads (upstream #40).

The library descends from resumable.js and moved to flow.js *for* resumability,
but shipped with the feature switched off -- and it had to be, because the
server's GET handler was broken three ways:

1. it read `request.form`, while flow.js sends test parameters in the **query
   string** on a GET, so every field came back empty;
2. it required a `file` part, which a GET never carries;
3. it answered "chunk missing" with **404**, which is in flow.js's
   `permanentErrors` list -- meaning that enabling chunk testing would have
   aborted every upload on its first chunk rather than uploading it.

The status codes are a protocol. From flow.js's own README:

    200/201/202  -> the chunk is assumed to have been completed
    permanent error -> upload is stopped
    anything else -> the chunk will be uploaded in the standard fashion

so "not present" must be a status in neither list; 204 is used here.

The interrupted-write tests matter most: trusting a half-written chunk on
resume produces a file that reassembles "successfully" into garbage, which is
much worse than re-sending it.
"""

import io

import flask
import pytest

from dash_uploader_ng.configure_upload import decorate_server
from dash_uploader_ng.httprequesthandler import (
    CHUNK_NOT_PRESENT_STATUS,
    HttpRequestHandler,
    get_chunk_name,
)

UPLOAD_API = "/API/dash-uploader"
UPLOAD_ID = "3e2f1c5a9c4b4e1a9a5e6c1f2b3d4e5f"
IDENTIFIER = "24-reportcsv"
FILENAME = "report.csv"

# flow.js's own defaults, which the server contract must respect.
FLOW_SUCCESS_STATUSES = {200, 201, 202}
FLOW_PERMANENT_ERRORS = {404, 413, 415, 500, 501}


@pytest.fixture
def upload_root(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    return root


@pytest.fixture
def client(upload_root):
    server = flask.Flask(__name__)
    server.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    decorate_server(
        server, str(upload_root), UPLOAD_API,
        http_request_handler=HttpRequestHandler, use_upload_id=True,
    )
    return server.test_client()


def params(chunk, chunks, content=b""):
    return {
        "flowChunkNumber": str(chunk),
        "flowTotalChunks": str(chunks),
        "flowCurrentChunkSize": str(len(content)),
        "flowFilename": FILENAME,
        "flowIdentifier": IDENTIFIER,
        "flowRelativePath": FILENAME,
        "upload_id": UPLOAD_ID,
    }


def post_chunk(client, content, chunk, chunks):
    form = params(chunk, chunks, content)
    form["file"] = (io.BytesIO(content), FILENAME)
    return client.post(UPLOAD_API, data=form, content_type="multipart/form-data")


def probe_chunk(client, chunk, chunks, content=b""):
    """The chunk-test GET, with parameters in the query string as flow.js sends them."""
    return client.get(UPLOAD_API, query_string=params(chunk, chunks, content))


def chunk_dir(upload_root):
    return upload_root / UPLOAD_ID / IDENTIFIER


class TestTheProtocolContract:
    def test_missing_chunk_is_not_a_flowjs_permanent_error(self, client):
        """The bug that forced testChunks off upstream."""
        status = probe_chunk(client, 1, 3, b"data").status_code

        assert status not in FLOW_PERMANENT_ERRORS, (
            f"{status} is in flow.js's permanentErrors -- returning it here aborts "
            "the entire upload instead of prompting the client to send the chunk"
        )
        assert status not in FLOW_SUCCESS_STATUSES, (
            f"{status} tells flow.js the chunk is already uploaded, so it would be "
            "skipped and the file would be reassembled with a hole in it"
        )
        assert status == CHUNK_NOT_PRESENT_STATUS

    def test_present_chunk_reports_a_success_status(self, client):
        content = b"chunk-one"
        assert post_chunk(client, content, 1, 3).status_code == 200

        status = probe_chunk(client, 1, 3, content).status_code
        assert status in FLOW_SUCCESS_STATUSES

    def test_the_get_reads_parameters_from_the_query_string(self, client):
        """Upstream read request.form, so a GET saw no parameters at all."""
        content = b"chunk-one"
        post_chunk(client, content, 1, 3)

        # Sent the way flow.js actually sends it: query string, no body.
        assert probe_chunk(client, 1, 3, content).status_code in FLOW_SUCCESS_STATUSES

        # And the parameters really are being read -- a different chunk number
        # must not report present.
        assert probe_chunk(client, 2, 3, content).status_code == CHUNK_NOT_PRESENT_STATUS

    def test_the_get_does_not_require_a_file_part(self, client):
        """A GET carries no body; upstream indexed request.files['file'] anyway."""
        response = probe_chunk(client, 1, 3, b"data")
        assert response.status_code == CHUNK_NOT_PRESENT_STATUS

    def test_a_hostile_upload_id_is_still_rejected_on_the_get(self, client):
        """The GET path must not be a way around the CVE-2026-38360 fix."""
        query = params(1, 1, b"x")
        query["upload_id"] = "../../../../site-packages"
        assert client.get(UPLOAD_API, query_string=query).status_code == 400


class TestResumingAnInterruptedUpload:
    def test_already_sent_chunks_are_reported_present_and_missing_ones_are_not(
        self, client
    ):
        parts = [b"aaaa", b"bbbb", b"cccc", b"dddd"]
        # Simulate an upload that died after two chunks.
        post_chunk(client, parts[0], 1, 4)
        post_chunk(client, parts[1], 2, 4)

        present = [
            probe_chunk(client, i, 4, parts[i - 1]).status_code in FLOW_SUCCESS_STATUSES
            for i in range(1, 5)
        ]
        assert present == [True, True, False, False]

    def test_resuming_produces_the_same_bytes_as_an_uninterrupted_upload(self, client, upload_root):
        parts = [b"aaaa", b"bbbb", b"cccc", b"dddd"]
        post_chunk(client, parts[0], 1, 4)
        post_chunk(client, parts[1], 2, 4)

        # A resuming client tests each chunk and only sends the missing ones.
        for i, part in enumerate(parts, start=1):
            if probe_chunk(client, i, 4, part).status_code in FLOW_SUCCESS_STATUSES:
                continue
            assert post_chunk(client, part, i, 4).status_code == 200

        target = upload_root / UPLOAD_ID / FILENAME
        assert target.read_bytes() == b"".join(parts)

    def test_a_completed_upload_leaves_nothing_to_resume(self, client, upload_root):
        content = b"only-chunk"
        post_chunk(client, content, 1, 1)

        # The temp chunk directory is removed on completion, so the chunk is
        # legitimately gone -- re-uploading the same file starts over, which is
        # correct rather than a resume failure.
        assert probe_chunk(client, 1, 1, content).status_code == CHUNK_NOT_PRESENT_STATUS
        assert (upload_root / UPLOAD_ID / FILENAME).read_bytes() == content


class TestInterruptedWritesAreNotTrusted:
    """A chunk that exists but is not intact must be re-sent, never skipped."""

    def test_a_truncated_chunk_is_not_reported_present(self, client, upload_root):
        content = b"0123456789"
        post_chunk(client, content, 1, 2)

        # Simulate a server killed part-way through writing the chunk.
        chunk_path = chunk_dir(upload_root) / get_chunk_name(FILENAME, 1)
        chunk_path.write_bytes(content[:4])

        assert probe_chunk(client, 1, 2, content).status_code == CHUNK_NOT_PRESENT_STATUS, (
            "a truncated chunk was reported as complete -- resuming would "
            "reassemble a corrupt file that looks like a successful upload"
        )

    def test_an_empty_chunk_is_not_reported_present(self, client, upload_root):
        content = b"0123456789"
        post_chunk(client, content, 1, 2)
        (chunk_dir(upload_root) / get_chunk_name(FILENAME, 1)).write_bytes(b"")

        assert probe_chunk(client, 1, 2, content).status_code == CHUNK_NOT_PRESENT_STATUS

    def test_a_chunk_with_a_stale_lock_file_is_not_reported_present(
        self, client, upload_root
    ):
        """A lock left behind by a crash means the write may not have finished."""
        content = b"0123456789"
        post_chunk(client, content, 1, 2)

        (chunk_dir(upload_root) / ".lock_1").write_text("")

        assert probe_chunk(client, 1, 2, content).status_code == CHUNK_NOT_PRESENT_STATUS

    def test_resuming_over_a_truncated_chunk_still_yields_correct_bytes(
        self, client, upload_root
    ):
        """The end-to-end version of the corruption case."""
        parts = [b"aaaaaaaa", b"bbbbbbbb"]
        post_chunk(client, parts[0], 1, 2)
        # Chunk 1 was only half-written before the crash.
        (chunk_dir(upload_root) / get_chunk_name(FILENAME, 1)).write_bytes(b"aaaa")

        for i, part in enumerate(parts, start=1):
            if probe_chunk(client, i, 2, part).status_code in FLOW_SUCCESS_STATUSES:
                continue
            post_chunk(client, part, i, 2)

        assert (upload_root / UPLOAD_ID / FILENAME).read_bytes() == b"".join(parts)


class TestTheResumableProp:
    def test_defaults_to_enabled(self):
        import dash_uploader_ng as du

        assert du.Upload(id="u").resumable is True

    def test_can_be_switched_off(self):
        import dash_uploader_ng as du

        assert du.Upload(id="u", resumable=False).resumable is False
