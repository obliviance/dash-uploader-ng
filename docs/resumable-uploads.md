# Resumable uploads

An upload interrupted by a network drop, a browser crash or a server restart
can pick up where it left off instead of starting again from zero.

This is **off by default** — turn it on per component:

```python
du.Upload(id="uploader")                   # not resumable (upstream behaviour)
du.Upload(id="uploader", resumable=True)   # resumable
```

## Why it is off by default

Upstream dash-uploader hard-coded flow.js's `testChunks` to `false`, so
switching it on changes the traffic an app generates: one extra `GET` to the
upload endpoint per chunk, roughly a thousand of them for a 1 GB upload at the
default chunk size. A reverse proxy, WAF or rate limiter tuned against upstream
would suddenly see requests it was never configured for, and the failure would
look like a broken upload rather than a policy hit.

Defaulting to off keeps `dash-uploader-ng` a drop-in replacement: swapping the
import changes nothing about what reaches your server. Opt in when you want the
feature, having checked that a `GET` to the upload path is allowed.

## Why it was broken

dash-uploader descends from resumable.js and moved to flow.js *for*
resumability — but shipped with the feature switched off
([#40](https://github.com/fohrloop/dash-uploader/issues/40)), and it had to be.
The server's `GET` handler could not have worked if it were on. It was broken
three ways at once:

1. **It read the wrong place.** flow.js sends its parameters in the multipart
   body on the upload `POST`, but in the **query string** on the chunk-test
   `GET`. The handler read `request.form` unconditionally, so every field came
   back empty.
2. **It required a file part.** `RequestData` indexed `request.files["file"]`,
   which a `GET` never carries.
3. **It answered 404.** This is the fatal one — see below.

The handler carried a comment reading *"Since testChunks is set to false, this
seems to be permanently disabled."*

## The status code is a protocol

When chunk testing is on, flow.js sends a `GET` before each chunk asking
whether the server already has it. From flow.js's README:

| Server responds | flow.js does |
| --------------- | ------------ |
| `200`, `201`, `202` | Chunk is already uploaded — **skip it** |
| A *permanent error* — by default `404`, `413`, `415`, `500`, `501` | **Abort the whole upload** |
| Anything else | Upload this chunk normally |

`404` is the intuitive answer for "not found", and it is exactly the wrong one:
it is in the permanent-error list, so enabling chunk testing upstream would
have killed every upload on its first chunk.

This fork answers **`204 No Content`**, which is in neither list.

## Not every chunk on disk can be trusted

A server killed part-way through writing a chunk leaves a partial file behind.
Skipping it on resume would reassemble a file that *looks* like a successful
upload and is silently corrupt — much worse than re-sending a megabyte.

A chunk is only reported as present when all of these hold:

- **No lock file.** The handler writes `.lock_<n>` before saving a chunk and
  removes it after. A lock left behind means the write was in progress or
  crashed part-way.
- **The size matches.** flow.js sends `flowCurrentChunkSize`; the file on disk
  must be exactly that many bytes. This catches a truncated write whose lock
  file did get cleaned up.
- **It is non-empty.** A zero-byte chunk is the signature of a write that never
  started.

`flowCurrentChunkSize` is client-supplied, so this is a correctness control
against interrupted writes, not a security control — an attacker can always
just send a chunk whose size matches. The security boundary is
[SECURITY.md](../SECURITY.md).

## The file is assembled even when the resume sends no `POST`

If an upload is interrupted *after* its last chunk has landed — a browser
crash, or the server going down between the final chunk write and the
reassembly — then on resume flow.js tests every chunk, is told each one is
present, and declares the file complete **without sending a single `POST`**.

The upload `POST` is where chunks are combined into the final file, so a resume
like that used to finish with nothing on disk: the component showed "complete",
`du.callback` fired, and the target file did not exist. The chunk-test `GET`
for the final chunk now runs the same completeness check and assembly the
`POST` does, so a fully-present upload is reassembled whether the last request
of the session was a `POST` or a `GET`.

## Resuming across a page reload

Chunks are stored under the upload's `upload_id`, and `du.Upload()` generates a
fresh `uuid.uuid1()` per component by default — so a page reload creates a new
folder and there is nothing to resume from.

Within one page session it works out of the box: a dropped connection, a paused
upload, or a server restart while the page stays open all resume.

To resume across reloads, supply an `upload_id` that is stable for the user's
session:

```python
du.Upload(id="uploader", upload_id=flask.session["upload_id"])
```

`upload_id` must be a single safe path segment — `[A-Za-z0-9._-]`, starting
with an alphanumeric. A UUID satisfies this.

## Cost

One extra `GET` per chunk. Each is small and answered with a couple of
filesystem calls, but at the default 1 MB chunk size a 1 GB upload means about
a thousand of them. If you are uploading many small files over a
high-latency link and do not need resumability, `resumable=False` removes them.

Raising `chunk_size` reduces the count for large files:

```python
du.Upload(id="uploader", chunk_size=16)   # 16 MB chunks
```
