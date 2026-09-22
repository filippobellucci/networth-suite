"""
Fixtures for the browser suite: build the frontend against the running
gateway, serve it the way production serves it, and open a page.

`serve -s` is what the Dockerfile uses, and the -s matters: it rewrites any
unknown path to index.html, which is what makes a single-page app's routes
work on a reload. A throwaway static server without that once made the
app's /assets route look broken when it was not, so the server below
reproduces the rewrite deliberately.
"""
from __future__ import annotations

import http.server
import os
import subprocess
import threading
from pathlib import Path

import pytest

from service_loader import REPO_ROOT

FRONTEND = REPO_ROOT / "frontend"


def pytest_collection_modifyitems(config, items):
    """Skips the browser suite, with a reason, when it cannot run."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        skip = pytest.mark.skip(reason="playwright is not installed (pip install playwright)")
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def chromium_path() -> str:
    import glob

    candidates = sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome"))
    candidates += sorted(glob.glob(
        os.path.expanduser("~/.cache/ms-playwright/chromium*/chrome-linux/chrome")))
    if not candidates:
        pytest.skip("no Chromium build found (run: playwright install chromium)")
    return candidates[-1]


@pytest.fixture(scope="session")
def built_frontend(stack) -> Path:
    """Builds the real production bundle, pointed at this run's gateway."""
    env = {**os.environ, "VITE_GATEWAY_URL": stack.gateway_url}
    result = subprocess.run(["npx", "vite", "build"], cwd=str(FRONTEND), env=env,
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"vite build failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return FRONTEND / "dist"


@pytest.fixture(scope="session")
def frontend_url(stack, built_frontend) -> str:
    root = str(built_frontend)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=root, **kwargs)

        def do_GET(self):  # noqa: N802 - http.server's naming
            path = self.path.split("?")[0]
            if path != "/" and not os.path.isfile(os.path.join(root, path.lstrip("/"))):
                self.path = "/index.html"   # the -s in `serve -s`
            return super().do_GET()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", stack.frontend_port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{stack.frontend_port}"
    server.shutdown()


@pytest.fixture
def page(chromium_path, frontend_url):
    """A browser page, with every console error and failed request recorded.

    Requests to fonts.googleapis.com are ignored: the page asks for them and
    a machine with no outbound network cannot answer, which says nothing
    about the application.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium_path, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.errors = []
        page.failures = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.on("requestfailed",
                lambda r: None if "fonts.googleapis.com" in r.url else page.failures.append(r.url))
        page.base = frontend_url
        yield page
        browser.close()
