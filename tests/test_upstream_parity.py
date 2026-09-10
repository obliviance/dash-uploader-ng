"""Differential tests: this fork's handler vs. the pristine upstream handler.

"Does the fork still behave like dash-uploader?" is not answerable by running
the fork's own tests, and upstream's browser suite only exercises the happy
path. So this module runs **both** handlers over the same corpus of requests
and diffs the outcomes.

`tests/_upstream/upstream_handler.py` is the unmodified
`dash_uploader/httprequesthandler.py` from upstream commit e1a1af4 (the last
commit before the repo was archived), with only its `from dash_uploader.utils
import retry` line repointed so it can be imported here. It is the real,
vulnerable code -- which is what makes the comparison meaningful.

Every request is served against a root inside pytest's `tmp_path`, so the
traversal cases genuinely escape the upload root but stay inside the test's own
temporary directory.

Two kinds of assertion live here:

1. **Parity** -- for legitimate traffic, the fork must do what upstream did:
   same status, same files in the same places, same bytes.
2. **Divergence, pinned deliberately** -- for hostile or malformed traffic the
   fork must *not* match upstream, and the exact intended difference is spelled
   out so it cannot drift silently later.
"""

import io

import flask
import pytest

from dash_uploader_ng.configure_upload import decorate_server
from dash_uploader_ng.httprequesthandler import HttpRequestHandler
from tests._upstream.upstream_handler import (
    HttpRequestHandler as UpstreamHttpRequestHandler,
)

UPLOAD_API = "/API/dash-uploader"

GOOD_UPLOAD_ID = "3e2f1c5a9c4b4e1a9a5e6c1f2b3d4e5f"
GOOD_IDENTIFIER = "11-reportcsv"
GOOD_FILENAME = "report.csv"


# The upload root is nested this deep inside each sandbox so that the published
# proof of concept -- which climbs four levels with "../../../../" -- still
# lands *inside* the sandbox. Without the padding, upstream's traversal escapes
# the test's own temp directory and litters the real filesystem, which is both
# antisocial and invisible to the assertions.
ROOT_PADDING = ("a", "b", "c", "d")


def build(handler_cls, root, use_upload_id=True):
    # The app name must not contain dots: Flask treats it as an import name and
    # older versions (dash 1.x pins werkzeug<2.1) try to resolve it as a module
    # when working out the static folder.
    name = "parity_" + handler_cls.__module__.replace(".", "_")
    server = flask.Flask(name)
    # Deliberately NOT TESTING=True: that propagates exceptions instead of
    # turning them into responses, and upstream's habit of returning None from
    # a failed view is exactly the behaviour being compared here.
    server.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    decorate_server(
        server,
        str(root),
        UPLOAD_API,
        http_request_handler=handler_cls,
        use_upload_id=use_upload_id,
    )
    return server.test_client()


def send(client, content=b"a,b\n1,2\n", *, chunk=1, chunks=1, **overrides):
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


def tree(root):
    """Every file under `root`, as paths relative to it, sorted."""
    return sorted(
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
    )


def escaped(sandbox, root):
    """Files written anywhere in the sandbox but OUTSIDE the upload root."""
    return sorted(
        str(p.relative_to(sandbox))
        for p in sandbox.rglob("*")
        if p.is_file() and root not in p.parents
    )


@pytest.fixture
def pair(tmp_path):
    """Two isolated sandboxes, one per handler, each with its own upload root.

    Callable more than once per test -- each call gets a fresh generation of
    sandboxes, so a test can compare several scenarios without one scenario's
    files bleeding into the next one's assertions.
    """
    generation = iter(range(1000))

    def _make(use_upload_id=True):
        base = tmp_path / f"run{next(generation)}"
        sandboxes, clients, roots = {}, {}, {}
        for name, cls in (
            ("upstream", UpstreamHttpRequestHandler),
            ("fork", HttpRequestHandler),
        ):
            sandbox = base / name
            root = sandbox.joinpath(*ROOT_PADDING, "uploads")
            root.mkdir(parents=True)
            sandboxes[name], roots[name] = sandbox, root
            clients[name] = build(cls, root, use_upload_id=use_upload_id)
        return clients, roots, sandboxes

    return _make


class TestLegitimateTrafficIsIdentical:
    """The fork must be a drop-in for everything a real client actually sends."""

    @pytest.mark.parametrize(
        "label,kwargs,content",
        [
            ("plain single chunk", {}, b"a,b\n1,2\n"),
            ("empty file", {}, b""),
            ("binary content", {}, bytes(range(256))),
            ("uuid1-style upload_id", {"upload_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"}, b"x"),
            ("uuid4 hex upload_id", {"upload_id": "8f14e45fceea167a5a36dedd4bea2543"}, b"x"),
            ("dotted filename", {"flowFilename": "archive.tar.gz", "flowIdentifier": "9-archivetargz"}, b"x"),
            ("underscored name", {"flowFilename": "my_report_2026.csv", "flowIdentifier": "9-myreport2026csv"}, b"x"),
            ("non-ascii filename", {"flowFilename": "données.csv", "flowIdentifier": "9-donnescsv"}, b"x"),
            ("cjk filename", {"flowFilename": "報告書.xlsx", "flowIdentifier": "9-xlsx"}, b"x"),
            ("cyrillic filename", {"flowFilename": "отчет.csv", "flowIdentifier": "9-csv"}, b"x"),
        ],
    )
    def test_same_status_same_files_same_bytes(self, pair, label, kwargs, content):
        clients, roots, _ = pair()

        results = {}
        for name in ("upstream", "fork"):
            response = send(clients[name], content, **kwargs)
            results[name] = (response.status_code, tree(roots[name]))

        assert results["fork"] == results["upstream"], (
            f"{label}: fork diverged from upstream.\n"
            f"  upstream -> {results['upstream']}\n"
            f"  fork     -> {results['fork']}"
        )
        # And the bytes actually landed intact on both.
        written = tree(roots["fork"])
        assert len(written) == 1
        assert (roots["fork"] / written[0]).read_bytes() == content

    def test_multi_chunk_reassembly_is_identical(self, pair):
        clients, roots, _ = pair()
        parts = [b"first-", b"second-", b"third"]

        for name in ("upstream", "fork"):
            for i, part in enumerate(parts, start=1):
                assert send(clients[name], part, chunk=i, chunks=len(parts)).status_code == 200

        assert tree(roots["fork"]) == tree(roots["upstream"])
        target = tree(roots["fork"])[0]
        assert (roots["fork"] / target).read_bytes() == b"".join(parts)
        assert (roots["fork"] / target).read_bytes() == (
            roots["upstream"] / target
        ).read_bytes()

    def test_reupload_overwrites_identically(self, pair):
        clients, roots, _ = pair()
        for name in ("upstream", "fork"):
            send(clients[name], b"first version")
            send(clients[name], b"second version")

        assert tree(roots["fork"]) == tree(roots["upstream"])
        target = tree(roots["fork"])[0]
        assert (roots["fork"] / target).read_bytes() == b"second version"

    def test_without_upload_id_is_identical(self, pair):
        clients, roots, _ = pair(use_upload_id=False)
        for name in ("upstream", "fork"):
            assert send(clients[name], b"payload").status_code == 200
        assert tree(roots["fork"]) == tree(roots["upstream"]) == [GOOD_FILENAME]


class TestHostileTrafficDivergesOnPurpose:
    """Where the fork must NOT match upstream, and exactly how."""

    # kwargs are built from the sandbox path so the absolute-path case can point
    # somewhere harmless. A literal "/etc/cron.d" would resolve to the real
    # /etc/cron.d -- `Path(root) / "/etc/cron.d"` discards root entirely -- and a
    # test must never aim a write there, even one expected to fail on
    # permissions.
    @pytest.mark.parametrize(
        "label,make_kwargs",
        [
            (
                "the published CVE PoC",
                lambda s: {"upload_id": "../../../../site-packages", "flowFilename": "evil.pth"},
            ),
            ("traversal via upload_id", lambda s: {"upload_id": "../escaped"}),
            ("absolute upload_id", lambda s: {"upload_id": str(s / "absolute-escape")}),
            ("dot-dot upload_id", lambda s: {"upload_id": ".."}),
        ],
    )
    def test_upstream_escapes_the_root_and_the_fork_does_not(self, pair, label, make_kwargs):
        clients, roots, sandboxes = pair()

        send(clients["upstream"], b"payload", **make_kwargs(sandboxes["upstream"]))
        send(clients["fork"], b"payload", **make_kwargs(sandboxes["fork"]))

        upstream_escapes = escaped(sandboxes["upstream"], roots["upstream"])
        fork_escapes = escaped(sandboxes["fork"], roots["fork"])

        # The vulnerability is real: prove upstream actually writes outside its
        # own upload root for this input. (If this ever stops being true the
        # test corpus is wrong, not the fix.)
        assert upstream_escapes, (
            f"{label}: expected upstream to escape its upload root, but it did "
            "not -- this case is not actually exercising the CVE"
        )
        # And the fork does not, anywhere.
        assert fork_escapes == [], f"{label}: fork wrote outside the upload root: {fork_escapes}"

    def test_flowidentifier_traversal_escapes_only_on_an_incomplete_upload(self, pair):
        """The flowIdentifier vector is real, but it hides itself.

        The escaped directory is the *temp chunk* directory, and upstream
        rmtree()s it once the upload completes -- so a single-chunk exploit
        leaves nothing behind and looks harmless. Declare more chunks than you
        send and the escaped chunk file simply stays there.

        Worth pinning precisely: a naive check using a complete upload would
        conclude this vector was not exploitable and might tempt someone into
        relaxing the validation on flowIdentifier.
        """
        clients, roots, sandboxes = pair()
        kwargs = {"flowIdentifier": "../../escaped"}

        # Complete upload: upstream cleans up after itself, nothing visible.
        send(clients["upstream"], b"payload", chunk=1, chunks=1, **kwargs)
        assert escaped(sandboxes["upstream"], roots["upstream"]) == []

        # Incomplete upload: the escaped chunk persists outside the root.
        clients, roots, sandboxes = pair()
        send(clients["upstream"], b"payload", chunk=1, chunks=2, **kwargs)
        assert escaped(sandboxes["upstream"], roots["upstream"]) != []

        # The fork refuses both, and writes nothing either way.
        for chunks in (1, 2):
            clients, roots, sandboxes = pair()
            response = send(clients["fork"], b"payload", chunk=1, chunks=chunks, **kwargs)
            assert response.status_code == 400
            assert escaped(sandboxes["fork"], roots["fork"]) == []
            assert tree(roots["fork"]) == []

    @pytest.mark.parametrize(
        "label,filename",
        [
            ("traversal attempt", "../../site-packages/evil.pth"),
            # flow.js itself only ever puts a bare name in flowFilename (the
            # path goes in flowRelativePath), so this is malformed input rather
            # than something a real client sends.
            ("folder-style path", "nested/dir/report.csv"),
        ],
    )
    def test_a_path_in_flowfilename_crashes_upstream_but_is_flattened_here(
        self, pair, label, filename
    ):
        """Upstream 500s; the fork flattens to a bare name and succeeds.

        Upstream never reaches the traversal: it tries to write the *chunk* to
        `<tempdir>/<path>_part_1` whose parent was never created, and dies with
        FileNotFoundError. So this vector is a denial of service upstream
        rather than an arbitrary write -- the advisory's framing of
        flowFilename is more pessimistic than the code actually is.
        """
        clients, roots, sandboxes = pair()

        upstream_status = send(clients["upstream"], b"payload", flowFilename=filename).status_code
        fork_response = send(clients["fork"], b"payload", flowFilename=filename)

        assert upstream_status == 500, f"{label}: expected upstream to crash"
        assert escaped(sandboxes["upstream"], roots["upstream"]) == []

        assert fork_response.status_code == 200
        assert escaped(sandboxes["fork"], roots["fork"]) == []
        assert tree(roots["fork"]) == [f"{GOOD_UPLOAD_ID}/{filename.rsplit('/', 1)[-1]}"]


class TestMalformedRequestsDivergeOnPurpose:
    """Upstream turned these into a confusing 500 (or a silent 200)."""

    @pytest.mark.parametrize(
        "label,kwargs",
        [
            ("missing flowTotalChunks", {"flowTotalChunks": ""}),
            # Just past the fork's MAX_CHUNKS (100_000). Deliberately not a
            # genuinely absurd value: upstream materialises one path per
            # claimed chunk with no cap, so "100000000" here makes *upstream*
            # hang for minutes on a single unauthenticated request -- which is
            # precisely the DoS the cap exists to prevent, but it also hangs
            # the test run, so it is demonstrated rather than reproduced.
            ("flowTotalChunks over the cap", {"flowTotalChunks": "10000001"}),
            ("chunk number out of range", {"chunk": 5, "chunks": 2}),
            ("empty filename", {"flowFilename": ""}),
        ],
    )
    def test_fork_returns_400_where_upstream_returned_500(self, pair, label, kwargs):
        clients, _, _ = pair()

        upstream_status = send(clients["upstream"], b"x", **kwargs).status_code
        fork_status = send(clients["fork"], b"x", **kwargs).status_code

        assert fork_status == 400, f"{label}: expected 400 from the fork, got {fork_status}"
        assert upstream_status != 400, (
            f"{label}: upstream unexpectedly returned 400 too -- this case no "
            "longer demonstrates a difference"
        )


class TestOddButHarmlessIdentifiers:
    """upload_ids that are unusual but not attacks.

    An earlier version of this fork refused all of these. None of them is a
    traversal -- each names one directory directly under the upload root -- and
    `upload_id` is a public parameter that apps derive from session data, so
    refusing them broke working applications for no security gain. They are
    pinned here as parity: the fork must accept what upstream accepted, and put
    the bytes in the same place.

    `safepath.STRICT_SEGMENTS` restores the old allow-list for deployments that
    want it; `TestStrictModeIsAvailable` covers that.
    """

    @pytest.mark.parametrize(
        "upload_id",
        [
            "user@example.com",     # a session e-mail
            "2024-01-15T10:30:00",  # an ISO timestamp
            "_private",             # leading underscore
            "user+tag",
            "my session",           # space
            "session:42",           # colon
            "café",                 # non-ascii
            ".hidden",              # leading dot
            "session.",             # trailing dot
        ],
    )
    def test_the_fork_accepts_them_exactly_as_upstream_did(self, pair, upload_id):
        clients, roots, sandboxes = pair()

        upstream = send(clients["upstream"], b"x", upload_id=upload_id)
        fork = send(clients["fork"], b"x", upload_id=upload_id)

        assert upstream.status_code == 200
        assert fork.status_code == 200
        # Same status, same bytes, same place -- and still inside the root.
        assert tree(roots["fork"]) == tree(roots["upstream"])
        assert escaped(sandboxes["fork"], roots["fork"]) == []


class TestStrictModeIsAvailable:
    """The narrow allow-list is still one assignment away."""

    def test_strict_segments_refuses_them_again(self, pair, monkeypatch):
        from dash_uploader_ng import safepath

        monkeypatch.setattr(safepath, "STRICT_SEGMENTS", True)
        clients, roots, sandboxes = pair()

        assert send(clients["fork"], b"x", upload_id="my session").status_code == 400
        assert tree(roots["fork"]) == []

    def test_strict_mode_does_not_affect_ordinary_ids(self, pair, monkeypatch):
        from dash_uploader_ng import safepath

        monkeypatch.setattr(safepath, "STRICT_SEGMENTS", True)
        clients, roots, _ = pair()

        assert send(clients["fork"], b"x", upload_id="sess-01").status_code == 200
