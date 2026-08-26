"""Complexity regression tests for chunk assembly (upstream #102, #30).

Upstream tested completeness by stat()ing all N chunks on *every* request,
which is O(N^2) syscalls across an upload. The 11.2 GB file in upstream #102 is
11468 chunks at the default 1 MB size, so roughly 131 million stat() calls --
the bulk of "two orders of magnitude slower than making a copy of the file".

These count filesystem calls rather than measuring wall time, because a timing
assertion would be flaky on shared CI. Counting is what actually pins the
complexity: a reintroduced per-chunk scan shows up immediately regardless of
how fast the machine is.
"""

import io
import os

import flask
import pytest

from dash_uploader_ng.configure_upload import decorate_server
from dash_uploader_ng.httprequesthandler import HttpRequestHandler

UPLOAD_API = "/API/dash-uploader"


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


def post_chunk(client, chunk, chunks, content=b"payload"):
    form = {
        "flowChunkNumber": str(chunk),
        "flowTotalChunks": str(chunks),
        "flowCurrentChunkSize": str(len(content)),
        "flowFilename": "big.bin",
        "flowIdentifier": "99-bigbin",
        "flowRelativePath": "big.bin",
        "upload_id": "sess",
        "file": (io.BytesIO(content), "big.bin"),
    }
    return client.post(UPLOAD_API, data=form, content_type="multipart/form-data")


class SyscallCounter:
    """Counts os.path.exists / os.listdir calls made during a block."""

    def __init__(self, monkeypatch):
        self.exists = 0
        self.listdir = 0
        real_exists, real_listdir = os.path.exists, os.listdir

        def counted_exists(path):
            self.exists += 1
            return real_exists(path)

        def counted_listdir(path="."):
            self.listdir += 1
            return real_listdir(path)

        monkeypatch.setattr(os.path, "exists", counted_exists)
        monkeypatch.setattr(os, "listdir", counted_listdir)


def test_an_in_progress_upload_does_not_scan_every_chunk(client, monkeypatch):
    """The heart of upstream #102.

    While an upload is still in progress, deciding "not complete yet" must not
    cost one filesystem call per chunk already uploaded. Upstream's cost grew
    with the chunk count; here it is flat.
    """
    n_chunks = 400

    # Prime with a chunk so the temp directory exists.
    post_chunk(client, 1, n_chunks)

    counter = SyscallCounter(monkeypatch)
    post_chunk(client, 2, n_chunks)

    # Upstream would have made ~n_chunks exists() calls for this single
    # request. A small constant is expected (lock file, target file, the
    # last-chunk gate); anything proportional to n_chunks is the regression.
    assert counter.exists < 20, (
        f"{counter.exists} os.path.exists calls for one mid-upload chunk with "
        f"{n_chunks} total chunks -- the per-chunk scan is back"
    )
    assert counter.listdir <= 1, (
        "the completeness check should not need a directory listing until the "
        "final chunk has arrived"
    )


@pytest.mark.parametrize("n_chunks", [50, 400])
def test_cost_per_chunk_does_not_grow_with_total_chunk_count(
    client, monkeypatch, n_chunks
):
    """Same work per chunk whether the file has 50 chunks or 400."""
    post_chunk(client, 1, n_chunks)

    counter = SyscallCounter(monkeypatch)
    post_chunk(client, 2, n_chunks)

    assert counter.exists < 20


def test_assembly_still_produces_the_right_bytes(client, upload_root):
    """The optimisation must not change the result."""
    parts = [bytes([i]) * 32 for i in range(1, 21)]

    for i, part in enumerate(parts, start=1):
        assert post_chunk(client, i, len(parts), part).status_code == 200

    target = upload_root / "sess" / "big.bin"
    assert target.read_bytes() == b"".join(parts)


def test_out_of_order_chunks_still_assemble_correctly(client, upload_root):
    """The cheap 'is the last chunk present' gate must not break out-of-order uploads.

    If the final chunk arrives first, the gate opens early and the full check
    runs on every subsequent request -- slower, but it must still be correct.
    """
    parts = [bytes([i]) * 16 for i in range(1, 11)]
    order = [10, 3, 1, 7, 2, 9, 4, 8, 5, 6]

    for i in order:
        assert post_chunk(client, i, len(parts), parts[i - 1]).status_code == 200

    target = upload_root / "sess" / "big.bin"
    assert target.read_bytes() == b"".join(parts)


def test_reassembly_streams_rather_than_reading_whole_chunks(
    client, upload_root, monkeypatch
):
    """Peak memory must not track chunk size.

    Upstream did `target.write(chunk.read())`, pulling an entire chunk into
    memory per iteration. Fine at the 1 MB default, but anyone raising
    chunk_size to make multi-gigabyte uploads bearable paid for it in RAM per
    concurrent upload.

    `shutil.copyfileobj` reads in bounded blocks, so asserting it is used is
    the implementation contract that keeps memory flat. (`BufferedReader.read`
    itself cannot be patched -- it is an immutable C type.)
    """
    import shutil

    from dash_uploader_ng import httprequesthandler

    calls = []
    real_copyfileobj = shutil.copyfileobj

    def spy(src, dst, *args, **kwargs):
        calls.append(getattr(src, "name", None))
        return real_copyfileobj(src, dst, *args, **kwargs)

    monkeypatch.setattr(httprequesthandler.shutil, "copyfileobj", spy)

    parts = [b"a" * 1024, b"b" * 1024, b"c" * 1024]
    for i, part in enumerate(parts, start=1):
        assert post_chunk(client, i, len(parts), part).status_code == 200

    # werkzeug's FileStorage.save() also uses copyfileobj (with an unnamed
    # source), so count only the reassembly reads of the chunk files.
    calls = [name for name in calls if name and "_part_" in str(name)]

    assert len(calls) == len(parts), (
        "reassembly did not stream every chunk through shutil.copyfileobj -- "
        "a whole chunk may be being read into memory at once"
    )
    assert (upload_root / "sess" / "big.bin").read_bytes() == b"".join(parts)
