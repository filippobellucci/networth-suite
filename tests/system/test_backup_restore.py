"""
Backup and restore, end to end through the gateway.

This is the only feature whose failure is unrecoverable, so it is tested as a
property rather than a checklist: take a deliberately awkward instance, record
what every read endpoint says, export, change the data, restore, and require
every one of those answers to come back identical.

Stated that way the test does not need to know which tables exist. A new
entity kind that the backup forgets to carry fails it automatically, which a
list of hand-written assertions would not.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.system, pytest.mark.slow]

TODAY = date.today()


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def factsheet() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Ripartizione Geografica"
    ws.append(["Paesi", "Peso"])
    for row in [("Stati Uniti", 0.62), ("Giappone", 0.13),
                ("Germania", 0.15), ("Francia", 0.10)]:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def seeded(stack):
    """An instance with one of everything, including the states that are easy
    to forget: an archived portfolio, an archived account, a voucher account,
    a partly refunded expense, a cross-currency transfer and a frozen
    snapshot."""
    import httpx

    gw = httpx.Client(base_url=stack.gateway_url, timeout=180)
    core = "/api/core"

    def post(path, **kw):
        r = gw.post(f"{core}{path}", **kw)
        assert r.status_code in (200, 201), f"{path} -> {r.status_code} {r.text[:200]}"
        return r.json()

    eur = post("/portfolios", json={"name": "BK euro", "base_currency": "EUR", "notes": "main"})
    usd = post("/portfolios", json={"name": "BK dollar", "base_currency": "USD"})
    old = post("/portfolios", json={"name": "BK archived", "base_currency": "EUR"})
    gw.patch(f"{core}/portfolios/{old['id']}", json={"archived": True})

    listed = post("/assets", json={"name": "BK world", "ticker": "TESTUSD", "isin": "IE00B4L5Y983",
                                   "asset_class": "ETF", "category": "STOCK", "currency": "USD"})
    manual = post("/assets", json={"name": "BK house", "asset_class": "REAL_ESTATE",
                                   "currency": "EUR", "notes": "manual valuation"})
    for n, q in ((30, 5), (20, 8), (10, 10)):
        post(f"/portfolios/{eur['id']}/holdings",
             json={"asset_id": listed["id"], "entry_date": days_ago(n), "quantity": q})
    post(f"/portfolios/{eur['id']}/holdings",
         json={"asset_id": manual["id"], "entry_date": days_ago(25),
               "quantity": 1, "manual_price": 250000})
    post(f"/portfolios/{usd['id']}/holdings",
         json={"asset_id": listed["id"], "entry_date": days_ago(15), "quantity": 42.5})

    accounts = {
        "cash": post(f"/portfolios/{eur['id']}/cash-accounts",
                     json={"name": "BK checking", "currency": "EUR", "institution": "A Bank"}),
        "usd": post(f"/portfolios/{eur['id']}/cash-accounts",
                    json={"name": "BK usd", "currency": "USD"}),
        "voucher": post(f"/portfolios/{eur['id']}/cash-accounts",
                        json={"name": "BK vouchers", "currency": "EUR",
                              "kind": "VOUCHER", "unit_value": 7.5}),
        "pension": post(f"/portfolios/{eur['id']}/cash-accounts",
                        json={"name": "BK pension", "currency": "EUR",
                              "category": "PENSION_FUND"}),
        "closed": post(f"/portfolios/{eur['id']}/cash-accounts",
                       json={"name": "BK closed", "currency": "EUR"}),
    }
    for key, amount in (("cash", 5000), ("usd", 1200), ("voucher", 40),
                        ("pension", 30000), ("closed", 900)):
        post(f"/cash-accounts/{accounts[key]['id']}/balances",
             json={"entry_date": days_ago(30), "balance": amount})

    category = post("/expense-categories", json={"name": "BK groceries"})
    post(f"/cash-accounts/{accounts['cash']['id']}/transactions",
         json={"entry_date": days_ago(12), "direction": "INCOME", "amount": 2500, "note": "salary"})
    expense = post(f"/cash-accounts/{accounts['cash']['id']}/transactions",
                   json={"entry_date": days_ago(8), "direction": "EXPENSE", "amount": 320.55,
                         "category_id": category["id"], "note": "weekly shop"})
    post(f"/cash-accounts/{accounts['cash']['id']}/transactions",
         json={"entry_date": days_ago(6), "direction": "INCOME", "amount": 100,
               "refund_of_id": expense["id"], "note": "partial refund"})
    post(f"/cash-accounts/{accounts['voucher']['id']}/transactions",
         json={"entry_date": days_ago(4), "direction": "EXPENSE", "quantity": 3})
    post("/transfers", json={"from_account_id": accounts["cash"]["id"],
                             "to_account_id": accounts["usd"]["id"],
                             "entry_date": days_ago(3), "amount": 500, "note": "top up"})
    gw.delete(f"{core}/cash-accounts/{accounts['closed']['id']}")
    post("/networth-snapshots", json={"currency": "EUR"})

    uploaded = gw.post(f"/api/geo/allocation/assets/{listed['id']}/upload",
                       files={"file": ("fund.xlsx", factsheet(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert uploaded.status_code == 200, uploaded.text[:300]

    yield {"gw": gw, "portfolios": [eur["id"], usd["id"], old["id"]]}
    gw.close()


def capture(gw, portfolio_ids) -> dict:
    """Everything a client can read, in one dictionary."""
    core = "/api/core"
    state = {
        "portfolios": gw.get(f"{core}/portfolios").json(),
        "portfolios_all": gw.get(f"{core}/portfolios", params={"include_archived": True}).json(),
        "assets": gw.get(f"{core}/assets").json(),
        "categories": gw.get(f"{core}/expense-categories").json(),
        "transactions": gw.get(f"{core}/transactions").json(),
        "snapshots": gw.get(f"{core}/networth-snapshots", params={"currency": "EUR"}).json(),
        "combined_totals": gw.get(f"{core}/networth/combined/totals").json(),
        "combined_history": gw.get(f"{core}/networth/combined").json(),
        "combined_growth": gw.get(f"{core}/networth/combined/growth").json(),
        "combined_xirr": gw.get(f"{core}/networth/combined/xirr").json(),
        "expenses": gw.get(f"{core}/expenses/summary", params={
            "from_date": "2000-01-01", "to_date": "2100-01-01", "currency": "EUR"}).json(),
        "geo_records": gw.get("/api/geo/allocation/assets").json(),
    }
    for pid in portfolio_ids:
        for name in ("snapshot", "history", "growth", "xirr", "holdings"):
            state[f"{name}:{pid}"] = gw.get(f"{core}/portfolios/{pid}/{name}").json()
        state[f"cash:{pid}"] = gw.get(f"{core}/portfolios/{pid}/cash-accounts",
                                      params={"include_archived": True}).json()
    return state


def test_a_backup_describes_what_it_contains(seeded):
    gw = seeded["gw"]
    archive = gw.get("/api/backup/export").content
    manifest = gw.post("/api/backup/preview",
                       files={"file": ("b.zip", archive, "application/zip")}).json()
    assert manifest["app"] == "networth-suite"
    assert manifest["core"]["portfolios"] >= 3
    assert manifest["core"]["cash_accounts"] >= 5
    assert manifest["geo"]["assets_with_files"] >= 1
    assert "exported_at" in manifest


def test_restoring_reproduces_the_instance_exactly(seeded):
    gw, ids = seeded["gw"], seeded["portfolios"]

    before = capture(gw, ids)
    archive = gw.get("/api/backup/export").content
    assert len(archive) > 0

    # Change the instance, so a restore that quietly did nothing would show up
    added = gw.post("/api/core/portfolios",
                    json={"name": "SHOULD NOT SURVIVE", "base_currency": "EUR"})
    assert added.status_code == 200
    assert capture(gw, ids)["portfolios"] != before["portfolios"]

    restored = gw.post("/api/backup/restore",
                       files={"file": ("b.zip", archive, "application/zip")})
    assert restored.status_code == 200, restored.text[:300]

    after = capture(gw, ids)
    differing = [key for key in before
                 if json.dumps(before[key], sort_keys=True) != json.dumps(after.get(key), sort_keys=True)]
    assert not differing, f"these did not survive the round trip: {differing}"
    assert "SHOULD NOT SURVIVE" not in json.dumps(after["portfolios"])


@pytest.mark.parametrize("payload,why", [
    (b"definitely not a database", "random bytes"),
    (b"", "an empty file"),
    (b"SQLite format 3\x00" + b"\x00" * 200, "the magic header and nothing valid after it"),
])
def test_a_core_member_that_is_not_a_database_is_refused(seeded, payload, why):
    """And refused as a bad request, without half-restoring the instance."""
    gw = seeded["gw"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "networth-suite", "exported_at": "x",
                                                 "core": {}, "geo": {}}))
        zf.writestr("core/networth.db", payload)
        zf.writestr("geo/fund-files.zip", b"PK\x05\x06" + b"\x00" * 18)
    response = gw.post("/api/backup/restore",
                       files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert 400 <= response.status_code < 500, f"{why} -> {response.status_code}"
    assert gw.get("/api/core/portfolios").status_code == 200, "the instance still serves"


def test_an_upload_that_is_not_a_backup_is_refused(seeded):
    gw = seeded["gw"]
    for payload in (b"hello", b"PK\x03\x04 not really"):
        response = gw.post("/api/backup/preview",
                           files={"file": ("b.zip", payload, "application/zip")})
        assert 400 <= response.status_code < 500


def test_a_zip_slip_entry_in_the_geo_half_is_refused(seeded, stack):
    gw = seeded["gw"]
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("../escaped.txt", b"x")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "networth-suite", "exported_at": "x",
                                                 "core": {}, "geo": {}}))
        zf.writestr("core/networth.db", (stack.core_data_dir / "networth.db").read_bytes())
        zf.writestr("geo/fund-files.zip", inner.getvalue())

    response = gw.post("/api/backup/restore",
                       files={"file": ("b.zip", outer.getvalue(), "application/zip")})
    assert 400 <= response.status_code < 500
    assert not (stack.geo_data_dir.parent / "escaped.txt").exists()
