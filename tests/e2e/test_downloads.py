"""
Firefox and WebKit, limited to the paths that produce a file: the backup
download and the transaction log's CSV export. Both go through the single
`api/client.downloadFile` (DESIGN_NOTES.md), which used to produce nothing
on these two browsers while passing on Chromium -- a detached <a> is
ignored by Firefox. That is why this file, not the rest of the suite, runs
on more than one engine: the other `test_ui.py` checks stay Chromium-only,
because running the whole page/interaction suite on three browsers would
slow every push down without covering anything new.
"""
from __future__ import annotations

import zipfile

import pytest

from test_ui import _ledger, _open_log

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_downloading_the_full_backup_produces_a_real_zip(download_browser_page):
    page = download_browser_page
    page.goto(f"{page.base}/settings", wait_until="networkidle")

    with page.expect_download() as dl:
        page.get_by_role("button", name="Download full backup").click()
    download = dl.value

    assert download.suggested_filename.startswith("networth-suite-backup-")
    assert download.suggested_filename.endswith(".zip")
    path = download.path()
    assert path is not None and path.stat().st_size > 0, "the download produced an empty file"
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert "manifest.json" in names, f"no manifest in the backup: {names}"
        assert "core/networth.db" in names, f"no core database in the backup: {names}"
    assert page.errors == [] and page.failures == []


def test_exporting_the_transaction_log_as_csv(download_browser_page, core_http):
    p, rev, other, txn, ok = _ledger(core_http, "Download tier e2e")
    txn("EXPENSE", 7.2, "Unicoop download tier e2e")

    _open_log(download_browser_page, "Download tier e2e")
    with download_browser_page.expect_download() as dl:
        download_browser_page.get_by_role("button", name="Export CSV").click()
    download = dl.value

    assert download.suggested_filename.startswith("transactions-")
    assert download.suggested_filename.endswith(".csv")
    path = download.path()
    assert path is not None and path.stat().st_size > 0, "the download produced an empty file"
    content = path.read_text(encoding="utf-8-sig")
    assert "Unicoop download tier e2e" in content, "the exported file has no rows"
    assert download_browser_page.errors == [] and download_browser_page.failures == []
