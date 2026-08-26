# Branching and release process

## Branches

| Branch | What it is | Who moves it |
| ------ | ---------- | ------------ |
| `stable` | The most recently **published** release, nothing more. Always equals the latest release tag. | The release workflow, automatically |
| `main` | Integration branch. Everything merged here has passed CI, but may not be released yet. | Merges from short-lived branches |
| `feature/*` | One new capability | Author, then merged into `main` and deleted |
| `fix/*` | One bug or performance fix | ” |
| `docs/*` | Documentation only | ” |
| `ci/*` | Build, workflow or tooling changes | ” |
| `security/*` | A vulnerability fix, usually with an advisory | ” |
| `release/vX.Y.Z` | Version bump + changelog for one release | Merged into `main`, then tagged |

**Never commit directly to `main` or `stable`.** Branch, get CI green, merge
with `--no-ff` so the merge commit records what the branch was for, then delete
the branch locally and on the remote.

### Which branch should I use?

`stable` is what to depend on if you are vendoring or pinning to a git ref —
it only ever moves to a version that was actually published to PyPI and passed
the full release gate.

`main` is where development happens. It is green, but it is not a release.

## Why `stable` exists

`main` moves whenever work lands, so a git ref pointing at it can pick up
unreleased changes. `stable` gives an unambiguous "what is the current
release" pointer that does not require reading tags, and it cannot drift ahead
of PyPI because only the publish workflow moves it — after the upload has
already succeeded.

## Release process

1. Branch `release/vX.Y.Z` off `main`.
2. Bump the version in **both** places, which must agree:
   - `pyproject.toml` → what pip and PyPI see
   - `package.json` → what `dash_uploader_ng.__version__` reports at runtime
     (it is read from the generated `_build/package-info.json`)
3. Add the release's entry to [`docs/CHANGELOG.md`](CHANGELOG.md) — what
   changed, for users.
4. Merge into `main` (CI must be green).
5. Tag `vX.Y.Z` and push the tag. This triggers the publish workflow, which
   builds, tests on 3.10–3.13, runs upstream's browser suite, publishes to PyPI
   via Trusted Publishing, and only then fast-forwards `stable`.
6. Add the release's entry to [`RELEASES.md`](../RELEASES.md) — what *happened*
   during the release, for maintainers.
7. Create the GitHub release with the built artifacts attached.

Full command-level detail is in [`RELEASING.md`](../RELEASING.md).

## `CHANGELOG.md` vs `RELEASES.md`

They are deliberately different documents and it is worth keeping them so:

- **[`docs/CHANGELOG.md`](CHANGELOG.md)** is for **users**: what changed in the
  software, per version. Added / Fixed / Changed.
- **[`RELEASES.md`](../RELEASES.md)** is the **release log**, for
  **maintainers**: what happened when each version was shipped. Dates, the CI
  run that gated it, what was verified and how, and anything that went wrong.
  It answers "was this release actually checked, and against what?" months
  later, when nobody remembers.

A version can appear in the changelog with a tidy feature list and still have a
release log entry noting that the first publish attempt failed, or that a
particular platform was never tested. That second record is the one that
matters when something turns out to be broken.

## Versioning

Semantic versioning, with the caveat that this is a fork of an archived
project: version numbers are this fork's own line and do not track upstream's.

- **Patch** — bug fixes, performance, docs.
- **Minor** — new capability, backwards compatible.
- **Major** — a change that requires consumers to edit code.

**A version can only be uploaded to PyPI once**, and deleting a release does
not free the number. If a release is wrong, bump to the next patch version
rather than trying to re-upload.
