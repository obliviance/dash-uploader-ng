# Releasing to PyPI

## The one thing that makes this package unusual

The importable package contains a **generated** subdirectory,
`dash_uploader_ng/_build/`: the webpack JS bundle plus the Python component
classes that `dash-generate-components` writes. It is **not in version
control** (see `.gitignore`), so a fresh clone does not have it.

**You must run `npm run build` before building the Python distribution.**

If you forget, the build fails loudly rather than shipping a broken artifact:

```
error: package directory 'dash_uploader_ng/_build' does not exist
```

That is by design — `pyproject.toml` lists `dash_uploader_ng._build` as an
explicit package, so setuptools refuses to continue rather than quietly
producing a wheel with no JS in it.

## Prerequisites

- Node ≥ 16.13 and npm ≥ 8.1.4 (to build the bundle)
- Python ≥ 3.10 with `build` and `twine`
- A PyPI account, and the project name registered to it (see below)

## Before the first upload

1. **Claim the name.** `dash-uploader-ng` was unregistered as of this writing.
   Names are first-come, first-served, and the *first successful upload*
   claims it — so upload to TestPyPI first, then to PyPI promptly.
2. **Set the maintainer metadata.** `pyproject.toml` still has a placeholder:
   ```toml
   maintainers = [{ name = "dash-uploader-ng maintainers" }]
   ```
   Replace it with your own name and (optionally) email. Note this becomes
   **public** on the PyPI page, so use an address you're willing to publish.
   Leave `authors` as upstream — that's the MIT attribution.
3. **Push the repo to GitHub** and confirm the URLs in `[project.urls]`
   resolve. The README badges and the demo GIF are absolute links to
   `github.com/obliviance/dash-uploader-ng`; until that repo is public, the
   images on the PyPI page will be broken.

## Release steps

```bash
# 0. clean state
git status                      # should be clean
rm -rf dist/ dash_uploader_ng/_build/

# 1. bump the version in BOTH places (they must match)
#      pyproject.toml  ->  [project] version
#      package.json    ->  "version"
#    package.json's value is what ends up in dash_uploader_ng.__version__,
#    because __init__.py reads _build/package-info.json.

# 2. build the JS bundle + generated component classes
npm ci
npm run build

# 3. build the sdist and wheel
python -m build

# 4. validate what you're about to publish
python -m twine check dist/*
unzip -l dist/*.whl | grep _build      # the JS bundle MUST be listed

# 5. upload to TestPyPI first and install it somewhere clean
python -m twine upload --repository testpypi dist/*
python -m pip install --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ dash-uploader-ng

# 6. the real thing
python -m twine upload dist/*

# 7. tag it
git tag -a v1.0.0 -m "dash-uploader-ng 1.0.0"
git push origin v1.0.0
```

Step 5's `--extra-index-url` matters: TestPyPI does not mirror `dash`, so the
dependency resolution fails without a fallback to real PyPI.

## Authentication: prefer Trusted Publishing

Don't paste API tokens into your shell if you can avoid it. GitHub Actions can
publish via OIDC with no long-lived secret at all — see
`.github/workflows/publish.yml` in this repo.

To enable it, on PyPI go to *Your projects → dash-uploader-ng → Publishing*
(or, before the first release, *Account → Publishing → Add a pending
publisher*) and register:

| Field             | Value                    |
| ----------------- | ------------------------ |
| Owner             | `obliviance`             |
| Repository        | `dash-uploader-ng`       |
| Workflow filename | `publish.yml`            |
| Environment       | `pypi`                   |

A **pending publisher** is what lets you use this for the very first upload,
before the project exists on PyPI.

If you'd rather use a token: create a scoped API token on PyPI, then
`twine upload -u __token__ -p pypi-...`, or put it in `~/.pypirc`.

## Versioning

The version lives in two files and they must agree:

- `pyproject.toml` — what pip/PyPI see
- `package.json` — what `dash_uploader_ng.__version__` reports at runtime

**A given version number can only be uploaded to PyPI once**, and deleting a
release does not free the number. If you get it wrong, bump to the next patch
version rather than trying to re-upload.

## What ships

Verify with `unzip -l dist/*.whl`:

- `dash_uploader_ng/*.py` — including `safepath.py`, the CVE-2026-38360 fix
- `dash_uploader_ng/_build/` — the JS bundle, source map, component classes
  and metadata

Not shipped: `tests/`, `src/` (JS sources), `node_modules/`, `devscripts/`.
