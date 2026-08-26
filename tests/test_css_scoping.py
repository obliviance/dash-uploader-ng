"""Regression tests for the CSS leak (upstream #91, #43, #25).

Upstream shipped Bootstrap 4's button and progress-bar rules with their
selectors unscoped -- `.btn`, `.progress`, and even the bare `progress` element
-- and webpack injects the stylesheet into `<head>` via style-loader. Importing
the component therefore restyled the *host* application: broken Font Awesome
icons (#91) and restyled unrelated buttons (#43), reported years apart as
separate mysteries.

The fix scopes every bundled rule beneath `.dash-uploader-root`, a class that is
always present on the component's own root element and is not user-overridable.

These tests read the built JS bundle, because that is what actually reaches a
browser -- a test against the source `.css` files would pass even if the build
stopped including them.
"""

import re
from pathlib import Path

import pytest

ROOT_CLASS = "dash-uploader-root"
BUNDLE = (
    Path(__file__).resolve().parent.parent
    / "dash_uploader_ng"
    / "_build"
    / "dash_uploader_ng.min.js"
)

# Selectors that would collide with a host application's own styles. Each was
# present unscoped upstream.
DANGEROUS = [
    ".btn",
    ".btn-primary",
    ".btn-secondary",
    ".btn-sm",
    ".btn-lg",
    ".progress",
    ".progress-bar",
    ".progress-bar-striped",
    ".fade",
]


@pytest.fixture(scope="module")
def bundle():
    if not BUNDLE.exists():
        pytest.skip(
            f"{BUNDLE.name} not built -- run `npm run build` first (see RELEASING.md)"
        )
    return BUNDLE.read_text(encoding="utf-8", errors="replace")


def test_the_bundle_actually_contains_the_stylesheets(bundle):
    # Guards the tests below: if the CSS stopped being bundled entirely they
    # would all pass vacuously.
    assert ROOT_CLASS in bundle
    assert ".btn" in bundle, "button.css does not appear to be in the bundle"
    assert ".progress-bar" in bundle, "progressbar.css does not appear to be in the bundle"


@pytest.mark.parametrize("selector", DANGEROUS)
def test_no_globally_scoped_rule_for_a_dangerous_selector(bundle, selector):
    """`.btn{...}` must never appear without the scope class in front of it.

    Minified CSS puts the rule body immediately after the selector, so a
    top-level rule looks like `.btn{display:inline-block`. A scoped one looks
    like `.dash-uploader-root .btn{...}`.
    """
    pattern = re.compile(re.escape(selector) + r"\s*\{")

    for match in pattern.finditer(bundle):
        # Look at what immediately precedes the selector. If the scope class is
        # not in the same compound selector, the rule is global.
        preceding = bundle[max(0, match.start() - 120) : match.start()]
        # The selector list is delimited by `{` `}` or `,`.
        boundary = max(
            preceding.rfind("}"), preceding.rfind("{"), preceding.rfind(",")
        )
        compound = preceding[boundary + 1 :]
        assert ROOT_CLASS in compound, (
            f"unscoped rule for {selector!r} in the built bundle: "
            f"...{preceding[-70:]!r}{selector}{{ -- this leaks into the host app"
        )


def test_bare_element_selectors_are_scoped(bundle):
    """`progress{...}` as a bare element selector is the worst offender.

    It cannot be overridden by a host app's class-based styles without raising
    specificity, and it applies to every <progress> on the page.
    """
    for match in re.finditer(r"(^|[{},;])\s*progress\s*\{", bundle):
        preceding = bundle[max(0, match.start() - 120) : match.start() + 1]
        assert ROOT_CLASS in preceding.rsplit("}", 1)[-1], (
            "unscoped bare `progress` element selector in the built bundle"
        )


def test_keyframes_survived_the_scoping_transform(bundle):
    """`from`/`to` inside @keyframes are stops, not selectors.

    A naive scoping pass rewrites them to `.dash-uploader-root from`, which
    silently kills the striped-progress animation -- it would not error, just
    never animate.
    """
    assert "@keyframes" in bundle
    assert f"{ROOT_CLASS} from" not in bundle
    assert f"{ROOT_CLASS} to" not in bundle


def test_component_root_always_carries_the_scope_class(bundle):
    """The scope is useless if the root element does not carry the class.

    The class is added in getClass() ahead of the user's `className`, so it
    survives a user overriding className entirely.
    """
    assert f'"{ROOT_CLASS}"' in bundle or f"'{ROOT_CLASS}'" in bundle, (
        "the root class is not emitted as a literal in the bundle -- getClass() "
        "may no longer be adding it"
    )
