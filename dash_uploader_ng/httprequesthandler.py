import logging
import os
import pathlib
import shutil
import time
import traceback

from flask import abort, request
from werkzeug.exceptions import HTTPException

from dash_uploader_ng.safepath import (
    UnsafePathError,
    ensure_within,
    safe_filename,
    safe_segment,
)
from dash_uploader_ng.utils import retry

logger = logging.getLogger(__name__)

# Guard against a client claiming an absurd chunk count: the completeness check
# below materialises one path per chunk, so an unbounded value is an easy way to
# make the server allocate a very large list on an unauthenticated request. At
# the 1 MB default chunk size this still allows a ~100 GB upload.
MAX_CHUNKS = 100_000

# Answer to flow.js's chunk-test GET meaning "not uploaded yet, send it".
#
# It must be a status that is in neither flow.js's `successStatuses`
# ([200, 201, 202] -> "already have it, skip") nor its `permanentErrors`
# ([404, 413, 415, 500, 501] -> "give up on the whole upload"). Upstream used
# 404, which is in the second list. 204 No Content is in neither and carries
# the right semantics.
CHUNK_NOT_PRESENT_STATUS = 204


def get_chunk_name(uploaded_filename, chunk_number):
    return f"{uploaded_filename}_part_{chunk_number}"


def remove_file(file):
    os.unlink(file)


class RequestData:
    # A helper class that contains data from the request
    # parsed into handier form.
    #
    # Every attribute set here is attacker-controlled: these are form fields on
    # an unauthenticated POST. Validation therefore happens *here*, at the
    # boundary, so that no downstream code has to remember to do it -- that
    # forgetting is exactly what CVE-2026-38360 was. See safepath.py.

    def __init__(self, request, require_file=True):
        """
        Parameters
        ----------
        request: flask.request
            The Flask request object
        require_file: bool
            Whether a `file` part must be present. True for the upload POST;
            False for the chunk-test GET, which by definition carries no body.

        Raises
        ------
        UnsafePathError
            If any client-supplied field that reaches the filesystem is not a
            safe path component.
        """
        # flow.js puts its parameters in the multipart body on the upload POST,
        # but in the QUERY STRING on the chunk-test GET (see prepareXhrRequest
        # in flow.js). Upstream read request.form unconditionally, so every
        # field came back empty on a GET -- one of three reasons chunk testing
        # could never have worked. Picking the source by method keeps the two
        # cases explicit, and stops a query parameter shadowing a form field on
        # a POST.
        values = request.form if request.method == "POST" else request.args

        # Available fields: https://github.com/flowjs/flow.js
        self.n_chunks_total = self._get_chunk_count(values)
        self.chunk_number = values.get("flowChunkNumber", default=1, type=int)
        if self.chunk_number is None or not 1 <= self.chunk_number <= self.n_chunks_total:
            raise UnsafePathError(
                f"flowChunkNumber={self.chunk_number} is out of range "
                f"1..{self.n_chunks_total}"
            )

        # Size of THIS chunk, per the client. Used to verify a chunk found on
        # disk during a resume is actually complete -- see
        # BaseHttpRequestHandler.chunk_is_complete.
        self.current_chunk_size = values.get("flowCurrentChunkSize", type=int)
        if self.current_chunk_size is not None and self.current_chunk_size < 0:
            raise UnsafePathError(
                f"flowCurrentChunkSize={self.current_chunk_size} is negative"
            )

        # Becomes a filename under the upload root, so directory components are
        # stripped rather than rejected -- flow.js sends a relative path here
        # when a folder is dropped in, and those are flattened by design.
        self.filename = safe_filename(
            values.get("flowFilename", default="", type=str),
            field="flowFilename",
        )

        # 'unique' identifier for the file that is being uploaded.
        # Made of the file size and file name (with relative path, if available).
        # Becomes a directory name, so it must be a single safe segment.
        self.unique_identifier = safe_segment(
            values.get("flowIdentifier", default="", type=str),
            field="flowIdentifier",
        )

        # flowRelativePath is the flowFilename with the directory structure
        # included; the path is relative to the chosen folder. Sanitised the
        # same way as flowFilename because HttpRequestHandler subclasses can
        # read it, even though this class does not use it itself.
        relative_path = values.get("flowRelativePath", default="", type=str)
        self.relative_path = (
            safe_filename(relative_path, field="flowRelativePath")
            if relative_path
            else self.filename
        )

        # Get the chunk data.
        # Type of `chunk_data`: werkzeug.datastructures.FileStorage
        self.chunk_data = request.files["file"] if require_file else None

        # Becomes a directory name directly under the upload root. This is the
        # field the published CVE-2026-38360 exploit used.
        upload_id = values.get("upload_id", default="", type=str)
        self.upload_id = safe_segment(upload_id, field="upload_id") if upload_id else ""

    @staticmethod
    def _get_chunk_count(values):
        n_chunks_total = values.get("flowTotalChunks", type=int)
        if n_chunks_total is None:
            # Upstream left this as None and blew up later with a TypeError
            # deep inside range(); fail here with something diagnosable.
            raise UnsafePathError("flowTotalChunks is missing or not an integer")
        if not 1 <= n_chunks_total <= MAX_CHUNKS:
            raise UnsafePathError(
                f"flowTotalChunks={n_chunks_total} is out of range 1..{MAX_CHUNKS}"
            )
        return n_chunks_total


class BaseHttpRequestHandler:

    remove_file = staticmethod(retry(wait_time=0.35, max_time=15.0)(remove_file))

    def __init__(self, server, upload_folder, use_upload_id):
        """
        Parameters
        ----------
        server: flask.Flask
            The flask server instance
        upload_folder: str
            The folder to use for uploads
        use_upload_id: bool
            Determines if the uploads are put into
            folders defined by a "upload id" (upload_id).
            If True, uploads will be put into `folder`/<upload_id>/;
            that is, every user (for example with different
            session id) will use their own folder. If False,
            all files from all sessions are uploaded into
            same folder (not recommended).

        """
        self.server = server
        self.upload_folder = pathlib.Path(upload_folder)
        self.use_upload_id = use_upload_id

    def _handle(self, method):
        """Run ``method``, mapping its failure modes onto HTTP responses.

        Upstream logged every exception and then returned ``None``, which Flask
        rejects as an invalid response -- so genuine failures surfaced as a 500
        by accident, and the ``abort()`` calls inside ``_get`` were swallowed
        and turned into 500s too. Being explicit here is what lets a rejected
        path come back as a 400 rather than looking like a server fault.
        """
        try:
            return method()
        except HTTPException:
            # abort() raised deliberately somewhere below -- it is already the
            # response we want, so let it through untouched.
            raise
        except UnsafePathError as error:
            logger.warning("Rejected unsafe upload request: %s", error)
            # 400 rather than 500: this is a malformed or hostile request, not
            # a server fault. flow.js has no retry budget by default, so this
            # surfaces to the user as an upload error instead of looping.
            abort(400, "Invalid upload request")
        except Exception:
            logger.error(traceback.format_exc())
            abort(500, "Upload failed")

    def post(self):
        return self._handle(self._post)

    def _post(self):

        r = RequestData(request)

        # make our temp directory
        upload_session_root = self.get_upload_session_root(r.upload_id)
        temporary_folder_for_file_chunks = ensure_within(
            upload_session_root, upload_session_root / r.unique_identifier
        )

        if not temporary_folder_for_file_chunks.exists():
            temporary_folder_for_file_chunks.mkdir(parents=True)

        # save the chunk data
        chunk_name = get_chunk_name(r.filename, r.chunk_number)
        chunk_file = ensure_within(
            temporary_folder_for_file_chunks,
            temporary_folder_for_file_chunks / chunk_name,
        )

        # make a lock file
        lock_file_path = temporary_folder_for_file_chunks / f".lock_{r.chunk_number}"

        with open(lock_file_path, "a"):
            os.utime(lock_file_path, None)

        r.chunk_data.save(chunk_file)
        self.remove_file(lock_file_path)

        self.assemble_if_complete(
            temporary_folder_for_file_chunks,
            upload_session_root,
            r.filename,
            r.n_chunks_total,
        )

        return r.filename

    def assemble_if_complete(
        self, chunk_folder, upload_session_root, filename, n_chunks_total
    ):
        """Combine the stored chunks into the final file once every chunk is in.

        Called from the upload POST after each chunk is saved, and from the
        chunk-test GET when the final chunk is found already present -- see
        ``_get`` for why the GET path is needed at all.

        Returns True only on the call that actually assembles the file; False
        when the upload is not complete yet or another request got there first.
        """
        # Cheap gate first: if the final chunk is not on disk the upload cannot
        # be complete, whatever else is. flow.js sends chunks in order by
        # default (simultaneousUploads=1), so for all but the last request this
        # is a single stat() and we stop here.
        #
        # Upstream instead stat()ed all N chunks on EVERY request, which is
        # O(N^2) syscalls across an upload: the 11.2 GB file in upstream #102 is
        # 11468 chunks at the default 1 MB, so ~131 million stat() calls -- the
        # bulk of "two orders of magnitude slower than a file copy". One
        # directory listing replaces N stat()s once the gate opens.
        last_chunk = os.path.join(
            chunk_folder, get_chunk_name(filename, n_chunks_total)
        )
        if not os.path.exists(last_chunk):
            return False

        present = self.chunk_files_present(chunk_folder, filename)
        if len(present) < n_chunks_total or not present.issuperset(
            get_chunk_name(filename, x) for x in range(1, n_chunks_total + 1)
        ):
            return False

        # Make sure all files are finished writing, but do not wait forever.
        tried = 0
        while self.locks_present(chunk_folder):
            tried += 1
            if tried >= 5:
                logger.error(
                    "Error uploading files with temporary_folder_for_file_chunks: %s.",
                    chunk_folder,
                )
                raise Exception(
                    "Error uploading files with temporary_folder_for_file_chunks: "
                    f"{chunk_folder}"
                )
            time.sleep(1)

        chunk_paths = [
            os.path.join(chunk_folder, get_chunk_name(filename, x))
            for x in range(1, n_chunks_total + 1)
        ]

        # Make sure some other request didn't trigger file reconstruction.
        target_file_name = ensure_within(
            upload_session_root, upload_session_root / filename
        )
        if os.path.exists(target_file_name):
            logger.info("File %s exists already. Overwriting..", target_file_name)
            self.remove_file(target_file_name)

        # Stream each chunk rather than reading it whole. Upstream's `.read()`
        # pulled an entire chunk into memory per iteration, so peak usage
        # tracked chunk_size -- fine at the 1 MB default, but anyone raising
        # chunk_size to make large uploads bearable (upstream #102, #30) paid
        # for it in RAM per concurrent upload.
        try:
            with open(target_file_name, "ab") as target_file:
                for p in chunk_paths:
                    with open(p, "rb") as stored_chunk_file:
                        shutil.copyfileobj(stored_chunk_file, target_file)
        except FileNotFoundError:
            # A concurrent request assembled the file and removed the chunk
            # folder between the completeness check above and here. Nothing to
            # do -- that request owns the result.
            return False

        self.server.logger.debug("File saved to: %s", target_file_name)
        shutil.rmtree(chunk_folder, ignore_errors=True)
        return True

    def get(self):
        return self._handle(self._get)

    @staticmethod
    def chunk_files_present(folder, filename):
        """Names of this file's chunks currently on disk, from one directory read.

        One readdir instead of one stat() per chunk. See the call site for why
        that difference dominates large uploads.
        """
        prefix = f"{filename}_part_"
        try:
            return {name for name in os.listdir(folder) if name.startswith(prefix)}
        except OSError:
            return set()

    @staticmethod
    def locks_present(folder):
        """Whether any chunk write is still in progress, from one directory read."""
        try:
            return any(name.startswith(".lock_") for name in os.listdir(folder))
        except OSError:
            return False

    def chunk_is_complete(self, chunk_file, lock_file, expected_size):
        """Whether a chunk found on disk can be trusted and skipped.

        Existence alone is not enough. A server killed mid-write leaves behind
        a partially written chunk, and trusting it would silently corrupt the
        reassembled file -- the upload would "succeed" and produce garbage,
        which is far worse than re-sending a megabyte.

        Two independent checks guard that:

        - a lock file for this chunk means a write was in progress (or crashed
          part-way), so the chunk is not trustworthy;
        - the size on disk must match the size the client says the chunk has,
          which catches a truncated write whose lock file did get cleaned up.

        `flowCurrentChunkSize` is client-supplied, so this is not a security
        control -- an attacker can always just send a matching chunk. It is a
        correctness control against interrupted writes.
        """
        if lock_file.exists():
            return False
        try:
            actual_size = os.path.getsize(chunk_file)
        except OSError:
            return False
        if expected_size is not None and actual_size != expected_size:
            return False
        # With no declared size, fall back to "non-empty": a zero-byte chunk is
        # the signature of a write that never got started.
        return actual_size > 0

    def _get(self):
        # flow.js sends a GET before each chunk when `testChunks` is enabled, to
        # ask whether that chunk is already on the server. Answering it is what
        # makes an interrupted upload resumable (upstream #40).
        #
        # The response codes are a protocol, not a courtesy:
        #   200/201/202  -> chunk already uploaded, skip it
        #   404/413/415/500/501 -> PERMANENT ERROR, flow.js aborts the upload
        #   anything else -> upload this chunk normally
        #
        # Upstream returned 404 for "not here yet", which is in that permanent
        # error list, so enabling chunk testing would have killed every upload
        # on its first chunk. 204 No Content is in neither list and is the
        # conventional answer. See docs/resumable-uploads.md.
        r = RequestData(request, require_file=False)

        upload_session_root = self.get_upload_session_root(r.upload_id)

        # chunk folder path based on the parameters
        temporary_folder_for_file_chunks = ensure_within(
            upload_session_root, upload_session_root / r.unique_identifier
        )

        # chunk path based on the parameters
        chunk_file = ensure_within(
            temporary_folder_for_file_chunks,
            temporary_folder_for_file_chunks
            / get_chunk_name(r.filename, r.chunk_number),
        )
        lock_file = temporary_folder_for_file_chunks / f".lock_{r.chunk_number}"
        self.server.logger.debug("Testing chunk: %s", chunk_file)

        if self.chunk_is_complete(chunk_file, lock_file, r.current_chunk_size):
            # This chunk is already on the server, so flow.js will skip it.
            #
            # When an interrupted upload resumes and every chunk is found
            # present, flow.js is satisfied by these test responses alone and
            # never sends a POST -- but `_post` is otherwise the only place that
            # combines the chunks, so the file would be reported complete to the
            # user and to `du.callback` while never actually being assembled.
            # (Upstream shipped with testChunks disabled, so this path could not
            # run.) flow.js tests chunks in order, so the test for the final
            # chunk is the point where the whole upload is known to be present;
            # assemble it here. If earlier chunks are still missing this is a
            # no-op and the last of those to be POSTed assembles as usual.
            if r.chunk_number == r.n_chunks_total:
                self.assemble_if_complete(
                    temporary_folder_for_file_chunks,
                    upload_session_root,
                    r.filename,
                    r.n_chunks_total,
                )
            return "OK"

        # Let flow.js know this chunk still needs uploading. Must not be 404.
        return "", CHUNK_NOT_PRESENT_STATUS

    def get_upload_session_root(self, upload_id):
        """Return the directory this request is allowed to write inside.

        ``upload_id`` has already been validated as a single safe path segment
        by :class:`RequestData`; the :func:`ensure_within` call is the second
        layer, and is what keeps this correct if a subclass overrides this
        method and reintroduces an unchecked join.
        """
        if not self.use_upload_id or not upload_id:
            return ensure_within(self.upload_folder, self.upload_folder)
        return ensure_within(self.upload_folder, self.upload_folder / upload_id)


class HttpRequestHandler(BaseHttpRequestHandler):
    # You may use the flask.request
    # and flask.session inside the methods of this
    # class when needed.
    #
    # Note: unlike upstream, a failing request now propagates as an HTTP error
    # response, so `post_after`/`get_after` run on success only. Override
    # `post`/`get` directly if you need a hook that also fires on failure.
    def __init__(self, *args, **kwargs):  # pylint: disable=useless-super-delegation
        super().__init__(*args, **kwargs)

    def post_before(self):
        pass

    def post(self):
        self.post_before()
        returnvalue = super().post()
        self.post_after()
        return returnvalue

    def post_after(self):
        pass

    def get_before(self):
        pass

    def get(self):
        self.get_before()
        returnvalue = super().get()
        self.get_after()
        return returnvalue

    def get_after(self):
        pass
