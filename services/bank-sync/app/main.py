import asyncio
import html
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, FileResponse

from . import models, enable_banking
from .csv_log import CSV_PATH
from .database import Base, engine, SessionLocal
from .links_config import sync_links_config_to_db
from .mcc_categories import build_resolver
from .scheduler import scheduler_loop
from .sync import sync_all, sync_link
from .config import PUBLIC_BASE_URL, CORE_SERVICE_URL, ACCESS_VALID_DAYS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bank-sync")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Net Worth Suite - Bank Sync")


@app.on_event("startup")
async def startup():
    db = SessionLocal()
    try:
        sync_links_config_to_db(db)
    finally:
        db.close()
    asyncio.create_task(scheduler_loop())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/transactions-log.csv")
def download_transactions_log():
    """Raw audit trail of every transaction JSON received from every linked
    bank, one row each -- see app/csv_log.py. 404s until the first
    transaction has actually been captured."""
    if not CSV_PATH.is_file():
        return PlainTextResponse("No transactions logged yet.", status_code=404)
    return FileResponse(CSV_PATH, media_type="text/csv", filename="transactions_log.csv")


# ---------------------------------------------------------------- Status page
@app.get("/", response_class=HTMLResponse)
def status_page():
    db = SessionLocal()
    try:
        links = db.query(models.BankLink).order_by(models.BankLink.label).all()
    finally:
        db.close()

    # A REMOVED link (label deleted from links.yaml) is kept only so its
    # SyncedTransaction history stays valid -- no longer actionable from
    # here, so it's left out of the status page entirely.
    links = [link for link in links if link.status != models.LinkStatus.REMOVED]

    rows = []
    for link in links:
        status_color = {
            models.LinkStatus.ACTIVE: "#2f6b4a",
            models.LinkStatus.PENDING: "#8f8a7c",
            models.LinkStatus.AUTHORIZING: "#a8862e",
            models.LinkStatus.EXPIRED: "#9c4a2e",
            models.LinkStatus.ERROR: "#9c4a2e",
        }.get(link.status, "#8f8a7c")
        safe_label = html.escape(link.label)
        # Only a link that was never successfully authorized yet says
        # "Authorize" -- everything else (active, expired, errored) is a
        # re-authorization of an existing one.
        never_authorized = link.status in (models.LinkStatus.PENDING, models.LinkStatus.AUTHORIZING)
        action = (
            f'<a href="/authorize/{safe_label}">{"Authorize" if never_authorized else "Re-authorize"}</a>'
        )
        last_synced = link.last_synced_at.strftime("%Y-%m-%d %H:%M UTC") if link.last_synced_at else "never"
        valid_until = link.valid_until.strftime("%Y-%m-%d") if link.valid_until else "—"
        # last_error can carry the `error` query param from the public,
        # browser-reachable /callback endpoint -- escape it before rendering,
        # since it's otherwise a stored-XSS sink on this status page.
        error = (
            f'<div style="color:#9c4a2e;font-size:12px">{html.escape(link.last_error)}</div>'
            if link.last_error
            else ""
        )
        rows.append(
            f"""
            <tr>
              <td>{html.escape(link.label)}</td>
              <td>{html.escape(link.aspsp_name)} ({html.escape(link.aspsp_country)})</td>
              <td><span style="color:{status_color};font-weight:600">{html.escape(link.status.value)}</span>{error}</td>
              <td>{last_synced}</td>
              <td>{valid_until}</td>
              <td>{action}</td>
            </tr>
            """
        )

    if not rows:
        body = (
            "<p>No links configured yet. Copy <code>links.example.yaml</code> to "
            "<code>links.yaml</code>, fill in your portfolio/account IDs, and restart "
            "this container. See README.md.</p>"
        )
    else:
        body = f"""
        <table cellpadding="8" style="border-collapse:collapse;width:100%">
          <thead>
            <tr style="text-align:left;border-bottom:2px solid #333">
              <th>Label</th><th>Bank</th><th>Status</th><th>Last synced</th><th>Consent valid until</th><th></th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        """

    return f"""
    <html>
      <head><title>Net Worth Suite - Bank Sync</title></head>
      <body style="font-family:-apple-system,sans-serif;max-width:900px;margin:40px auto;padding:0 20px">
        <h1>Bank Sync</h1>
        <p>Automatic expense capture from your bank accounts via Enable Banking.</p>
        {body}
        <p style="margin-top:24px"><a href="/sync-now">Sync all now</a> · <a href="/transactions-log.csv">Download raw transactions log (CSV)</a></p>
      </body>
    </html>
    """


# ---------------------------------------------------------------- Authorization flow
@app.get("/authorize/{label}")
async def authorize(label: str):
    db = SessionLocal()
    try:
        link = db.get(models.BankLink, label)
        if not link:
            return PlainTextResponse(f"No link named {label!r} in links.yaml", status_code=404)

        # We embed the label in our own redirect_url so /callback knows
        # which link this authorization belongs to, without depending on
        # Enable Banking echoing back a "state" field in a specific shape.
        redirect_url = f"{PUBLIC_BASE_URL}/callback?{urlencode({'link': label})}"
        try:
            result = await enable_banking.start_authorization(
                link.aspsp_name, link.aspsp_country, redirect_url, ACCESS_VALID_DAYS
            )
        except enable_banking.EnableBankingError as e:
            link.status = models.LinkStatus.ERROR
            link.last_error = str(e)
            db.commit()
            return PlainTextResponse(f"Could not start authorization: {e}", status_code=502)

        link.status = models.LinkStatus.AUTHORIZING
        db.commit()

        auth_url = result.get("url") or result.get("link") or result.get("redirect_url")
        if not auth_url:
            link.status = models.LinkStatus.ERROR
            link.last_error = f"No redirect URL in Enable Banking response: {result}"
            db.commit()
            return PlainTextResponse(
                "Enable Banking didn't return a redirect URL -- check the container logs "
                "(the raw response was logged) and see enable_banking.py's honesty note.",
                status_code=502,
            )
        return RedirectResponse(auth_url)
    finally:
        db.close()


@app.get("/callback")
async def callback(link: str = Query(...), code: str | None = Query(None), error: str | None = Query(None)):
    db = SessionLocal()
    try:
        bank_link = db.get(models.BankLink, link)
        if not bank_link:
            return PlainTextResponse(f"Unknown link {link!r}", status_code=404)

        if error or not code:
            bank_link.status = models.LinkStatus.ERROR
            bank_link.last_error = error or "No authorization code returned"
            db.commit()
            return RedirectResponse("/")

        try:
            session = await enable_banking.finalize_session(code)
        except enable_banking.EnableBankingError as e:
            bank_link.status = models.LinkStatus.ERROR
            bank_link.last_error = str(e)
            db.commit()
            return RedirectResponse("/")

        accounts = session.get("accounts") or []
        if not accounts:
            bank_link.status = models.LinkStatus.ERROR
            bank_link.last_error = f"Session returned no accounts: {session}"
            db.commit()
            return RedirectResponse("/")

        # If the bank session covers more than one account (e.g. multiple
        # Revolut currency wallets), the first one is used by default.
        # Point cash_account_id at a *different* Net Worth Suite account
        # and re-authorize if you actually wanted a different one -- there's
        # no picker here on purpose, to keep this service simple.
        first_account = accounts[0]
        bank_link.session_id = session.get("session_id") or session.get("id")
        bank_link.eb_account_id = first_account if isinstance(first_account, str) else first_account.get("uid") or first_account.get("account_id")
        if not bank_link.eb_account_id:
            # The account entry didn't have any of the shapes we know how to
            # read (see enable_banking.py's honesty note on exact field
            # names) -- flipping to ACTIVE anyway would look identical to a
            # healthy link on the status page while sync.py's `not
            # link.eb_account_id` guard silently no-ops every cycle forever.
            bank_link.status = models.LinkStatus.ERROR
            bank_link.last_error = f"Could not resolve an account id from the session response: {first_account!r}"
            db.commit()
            return RedirectResponse("/")
        bank_link.status = models.LinkStatus.ACTIVE
        # Consent validity window -- must match the ACCESS_VALID_DAYS we asked
        # Enable Banking for in start_authorization(), not the authorization
        # instant itself. Previously this had no offset added, so every link
        # was flipped straight back to EXPIRED by sync.py's `valid_until <
        # utcnow()` check the moment the next sync cycle ran.
        bank_link.valid_until = datetime.utcnow().replace(microsecond=0) + timedelta(days=ACCESS_VALID_DAYS)
        bank_link.last_error = None
        db.commit()

        # Do an immediate first sync so you see results right away instead
        # of waiting up to SYNC_INTERVAL_HOURS.
        resolver = await build_resolver()
        await sync_link(db, bank_link, resolver)

        return RedirectResponse("/")
    finally:
        db.close()


# ---------------------------------------------------------------- Manual controls & helpers
@app.get("/sync-now")
async def sync_now():
    results = await sync_all()
    return results or RedirectResponse("/")


@app.get("/helper/aspsps")
async def helper_aspsps(country: str):
    """Lists banks Enable Banking supports for a country -- use this to find
    the exact `aspsp_name` for your links.yaml entries."""
    try:
        return await enable_banking.list_aspsps(country)
    except enable_banking.EnableBankingError as e:
        return PlainTextResponse(str(e), status_code=502)


@app.get("/helper/categories")
async def helper_categories():
    """Lists your existing Expense Categories with their exact names -- copy
    these names verbatim into mcc_categories.yaml (case doesn't matter, but
    spelling does)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{CORE_SERVICE_URL}/expense-categories")
        r.raise_for_status()
        return r.json()


@app.get("/helper/accounts")
async def helper_accounts():
    """Lists every portfolio and cash account in your Net Worth Suite
    instance, with their ids -- use this to fill in `portfolio_id` and
    `cash_account_id` in links.yaml without digging through the database."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        portfolios = (await client.get(f"{CORE_SERVICE_URL}/portfolios")).json()
        out = []
        for p in portfolios:
            accounts = (await client.get(f"{CORE_SERVICE_URL}/portfolios/{p['id']}/cash-accounts")).json()
            out.append(
                {
                    "portfolio_id": p["id"],
                    "portfolio_name": p["name"],
                    "cash_accounts": [{"cash_account_id": a["id"], "name": a["name"], "kind": a["kind"]} for a in accounts],
                }
            )
        return out
