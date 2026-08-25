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

    def __init__(self, request):
        """
        Parameters
        ----------
        request: flask.request
            The Flask request object

        Raises
        ------
        UnsafePathError
            If any client-supplied field that reaches the filesystem is not a
            safe path component.
        """
        # Available fields: https://github.com/flowjs/flow.js
        self.n_chunks_total = self._get_chunk_count(request)
        self.chunk_number = request.form.get("flowChunkNumber", default=1, type=int)
        if self.chunk_number is None or not 1 <= self.chunk_number <= self.n_chunks_total:
            raise UnsafePathError(
                f"flowChunkNumber={self.chunk_number} is out of range "
                f"1..{self.n_chunks_total}"
            )

        # Becomes a filename under the upload root, so directory components are
        # stripped rather than rejected -- flow.js sends a relative path here
        # when a folder is dropped in, and those are flattened by design.
        self.filename = safe_filename(
            request.form.get("flowFilename", default="", type=str),
            field="flowFilename",
        )

        # 'unique' identifier for the file that is being uploaded.
        # Made of the file size and file name (with relative path, if available).
        # Becomes a directory name, so it must be a single safe segment.
        self.unique_identifier = safe_segment(
            request.form.get("flowIdentifier", default="", type=str),
            field="flowIdentifier",
        )

        # flowRelativePath is the flowFilename with the directory structure
        # included; the path is relative to the chosen folder. Sanitised the
        # same way as flowFilename because HttpRequestHandler subclasses can
        # read it, even though this class does not use it itself.
        relative_path = request.form.get("flowRelativePath", default="", type=str)
        self.relative_path = (
            safe_filename(relative_path, field="flowRelativePath")
            if relative_path
            else self.filename
        )

        # Get the chunk data.
        # Type of `chunk_data`: werkzeug.datastructures.FileStorage
        self.chunk_data = request.files["file"]

        # Becomes a directory name directly under the upload root. This is the
        # field the published CVE-2026-38360 exploit used.
        upload_id = request.form.get("upload_id", default="", type=str)
        self.upload_id = safe_segment(upload_id, field="upload_id") if upload_id else ""

    @staticmethod
    def _get_chunk_count(request):
        n_chunks_total = request.form.get("flowTotalChunks", type=int)
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

        # check if the upload is complete
        chunk_paths = [
            os.path.join(
                temporary_folder_for_file_chunks, get_chunk_name(r.filename, x)
            )
            for x in range(1, r.n_chunks_total + 1)
        ]
        upload_complete = all([os.path.exists(p) for p in chunk_paths])

        # combine all the chunks to create the final file
        if upload_complete:

            # Make sure all files are finished writing
            # but do not wait forever..
            tried = 0
            while any(
                [
                    os.path.isfile(
                        os.path.join(
                            temporary_folder_for_file_chunks, ".lock_{:d}".format(chunk)
                        )
                    )
                    for chunk in range(1, r.n_chunks_total + 1)
                ]
            ):
                tried += 1
                if tried >= 5:
                    logger.error(
                        "Error uploading files with temporary_folder_for_file_chunks: %s.",
                        temporary_folder_for_file_chunks,
                    )
                    raise Exception(
                        "Error uploading files with temporary_folder_for_file_chunks: "
                        f"{temporary_folder_for_file_chunks}"
                    )
                time.sleep(1)

            # Make sure some other chunk didn't trigger file reconstruction
            target_file_name = ensure_within(
                upload_session_root, upload_session_root / r.filename
            )
            if os.path.exists(target_file_name):
                logger.info("File %s exists already. Overwriting..", target_file_name)
                self.remove_file(target_file_name)

            with open(target_file_name, "ab") as target_file:
                for p in chunk_paths:
                    with open(p, "rb") as stored_chunk_file:
                        target_file.write(stored_chunk_file.read())
            self.server.logger.debug("File saved to: %s", target_file_name)
            shutil.rmtree(temporary_folder_for_file_chunks)

        return r.filename

    def get(self):
        return self._handle(self._get)

    def _get(self):
        # flow.js uses a GET request to check if it uploaded the file already.
        # https://github.com/flowjs/flow.js/
        # TODO: Since testChunks is set to false, this seems to be permanently disabled.
        #       Should this be removed altogether?

        r = RequestData(request)

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
        self.server.logger.debug("Getting chunk: %s", chunk_file)

        if os.path.isfile(chunk_file):
            # Let flow.js know this chunk already exists
            return "OK"
        else:
            # Let flow.js know this chunk does not exists
            # and needs to be uploaded
            abort(404, "Not found")

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
