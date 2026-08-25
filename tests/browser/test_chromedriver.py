"""
A module to test that a working ChromeDriver/Chrome pair is available for the
browser tests.

The tests in this module are ran before other tests.
(ordering is edited in the conftest.py:pytest_collection_modifyitems)

Upstream this test called a bare ``webdriver.Chrome()`` and, on failure, told
you to reinstall the ``chromedriver-binary`` pip package. Two problems with
that: the package is abandoned, and a bare constructor ignores the options the
rest of the suite actually runs with (headless, --no-sandbox, an explicit
binary location), so it could never pass in a container or on CI even when the
suite itself was perfectly runnable.

It now launches with the *same* options as every other test, so it is a real
smoke check of the pair the suite will use rather than a check of one specific
way of installing a driver.
"""

import os

import pytest
from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

from .conftest import pytest_setup_options

BROKEN_DRIVER_ERROR_MSG = """
        !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        !!!                                      !!!
        !!! Could not start Chrome + ChromeDriver !!!
        !!!                                      !!!
        !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        The browser tests cannot run. Either:

          * let Selenium Manager fetch a matching pair automatically
            (it ships with selenium >= 4.6 -- just make sure Chrome is
            installed), or

          * point the suite at an explicit pair:

                export CHROME_BINARY=/path/to/chrome
                export CHROMEDRIVER=/path/to/chromedriver

        The underlying error was:

        {error}
        """


def test_chromedriver_version_okay():
    """Chrome and ChromeDriver start and agree on a version."""
    options = pytest_setup_options()

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
    except (SessionNotCreatedException, WebDriverException) as error:
        pytest.fail(BROKEN_DRIVER_ERROR_MSG.format(error=error))
    else:
        caps = driver.capabilities
        browser_version = caps.get("browserVersion", "?")
        driver_version = (
            caps.get("chrome", {}).get("chromedriverVersion", "?").split(" ")[0]
        )
        print(f"Chrome {browser_version} / ChromeDriver {driver_version}")

        # A mismatched major version is the classic cause of confusing
        # failures later in the suite, so surface it here instead.
        assert browser_version.split(".")[0] == driver_version.split(".")[0], (
            f"Chrome ({browser_version}) and ChromeDriver ({driver_version}) "
            "have different major versions"
        )
    finally:
        if driver is not None:
            driver.quit()


def test_browser_env_paths_exist_if_set():
    """If CHROME_BINARY / CHROMEDRIVER are set, they must actually point at files.

    A typo in either silently falls back to whatever is on PATH, which makes
    "why is it using the wrong browser?" needlessly hard to debug.
    """
    for var in ("CHROME_BINARY", "CHROMEDRIVER"):
        value = os.environ.get(var)
        if value:
            assert os.path.exists(value), f"${var} is set to {value!r}, which does not exist"
