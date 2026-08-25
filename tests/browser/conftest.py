import os
import shutil
from collections import defaultdict

from selenium import webdriver


def pytest_setup_options():
    """ChromeOptions used by dash.testing's `dash_duo` fixture.

    Upstream assumed a developer's desktop Chrome plus the `chromedriver_binary`
    pip package. That package is abandoned and pins an exact Chrome build, which
    makes the suite unrunnable on CI and in containers. Instead:

    - The browser binary and driver can be pointed at explicitly with the
      CHROME_BINARY / CHROMEDRIVER environment variables. If unset, Selenium
      Manager (bundled with selenium >= 4.6) resolves them automatically.
    - Headless is the default so the suite runs without a display. Set
      DASH_UPLOADER_HEADED=1 to watch a run in a real window while debugging.
    """
    options = webdriver.ChromeOptions()

    # Removes a bunch of errors on Windows, like
    # USB: usb_device_win.cc:93 Failed to read descriptors from ...
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    chrome_binary = os.environ.get("CHROME_BINARY")
    if chrome_binary:
        options.binary_location = chrome_binary

    if not os.environ.get("DASH_UPLOADER_HEADED"):
        options.add_argument("--headless=new")

    # Required in containers: no user namespaces for the sandbox, and /dev/shm
    # is typically too small for Chrome's default shared-memory use.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    return options


def pytest_configure(config):
    """Put an explicitly configured chromedriver on PATH.

    dash.testing constructs the driver itself, so the only portable way to hand
    it a specific chromedriver is to make sure that one is found first.
    """
    chromedriver = os.environ.get("CHROMEDRIVER")
    if chromedriver and os.path.exists(chromedriver):
        driver_dir = os.path.dirname(os.path.abspath(chromedriver))
        os.environ["PATH"] = driver_dir + os.pathsep + os.environ.get("PATH", "")


def pytest_report_header(config):
    driver = os.environ.get("CHROMEDRIVER") or shutil.which("chromedriver") or "(auto)"
    browser = os.environ.get("CHROME_BINARY") or "(auto)"
    headed = "headed" if os.environ.get("DASH_UPLOADER_HEADED") else "headless"
    return f"browser suite: {headed} | chrome={browser} | chromedriver={driver}"


def pytest_collection_modifyitems(items):
    """
    Modifies test items to ensure test modules run in a given order.
    """
    N_items = len(items)
    # The test_chromedriver.py has tests that test
    # it the tests can be run; run it first.
    FIRST_MODULES = ["tests.browser.test_chromedriver", "tests.browser.test_usage"]

    items_mapping = defaultdict(list)
    for item in items:
        items_mapping[item.module.__name__].append(item)

    sorted_items = []
    for modulename in FIRST_MODULES:
        sorted_items += items_mapping.pop(modulename, [])
    # all other modules
    for modulename, moduleitems in items_mapping.items():
        sorted_items += moduleitems

    items[:] = sorted_items
    assert (
        len(items) == N_items
    ), "Tests dropped out in reordering! This should never happen."
    return items