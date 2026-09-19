"""
Thin client for the Enable Banking API (https://enablebanking.com/docs/api/).

IMPORTANT HONESTY NOTE: this is written against Enable Banking's published
documentation as of when this file was created, not against a live test run
(there's no way to test against a real bank from this project's own dev
environment). The endpoint paths and the overall auth-code-exchange flow
are correct in shape, but Enable Banking's exact request/response field
names can and do change -- if authorization or syncing fails with a 4xx
error, check the response body (logged) against their current API
reference at https://enablebanking.com/docs/api/reference/ and adjust the
field names below. This is the one part of this service most likely to
need a small adjustment after your first real test.
"""
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
import jwt

from .config import ENABLE_BANKING_APP_ID, ENABLE_BANKING_PRIVATE_KEY_PATH, ENABLE_BANKING_BASE_URL

logger = logging.getLogger("bank-sync.enable_banking")


class EnableBankingError(RuntimeError):
    pass


def _private_key() -> str:
    path = Path(ENABLE_BANKING_PRIVATE_KEY_PATH)
    if not path.exists():
        raise EnableBankingError(
            f"Private key not found at {path} -- mount your Enable Banking app's "
            "private key PEM file there (see README.md)."
        )
    return path.read_text()


def _signed_jwt() -> str:
    if not ENABLE_BANKING_APP_ID:
        raise EnableBankingError("ENABLE_BANKING_APP_ID is not set -- see README.md.")
    now = int(time.time())
    payload = {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + 3600}
    # `kid` (key id) identifies which of your registered apps signed this
    # request -- Enable Banking's app id, per their JWT auth documentation.
    headers = {"kid": ENABLE_BANKING_APP_ID}
    return jwt.encode(payload, _private_key(), algorithm="RS256", headers=headers)


async def _request(method: str, path: str, **kwargs) -> dict:
    token = _signed_jwt()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    headers["Accept"] = "application/json"
    async with httpx.AsyncClient(base_url=ENABLE_BANKING_BASE_URL, timeout=30.0) as client:
        r = await client.request(method, path, headers=headers, **kwargs)
        if r.status_code >= 400:
            logger.warning("Enable Banking %s %s -> %s: %s", method, path, r.status_code, r.text[:2000])
            raise EnableBankingError(f"{method} {path} failed with {r.status_code}: {r.text[:500]}")
        return r.json()


async def list_aspsps(country: str) -> list[dict]:
    """Available banks ("ASPSPs") for a country -- use this to find the
    exact `aspsp_name` to put in links.yaml for your bank."""
    data = await _request("GET", "/aspsps", params={"country": country})
    return data.get("aspsps", data if isinstance(data, list) else [])


async def start_authorization(
    aspsp_name: str, aspsp_country: str, redirect_url: str, valid_days: int, historical_days: int
) -> dict:
    """
    Starts the bank-login flow. Returns a dict containing (among other
    things) a `url` to redirect the user's browser to -- opening it takes
    them to their bank's real login page.

    `historical_days` (MAX_HISTORICAL_DAYS) is accepted here but deliberately
    NOT placed into the request body: Enable Banking's `/auth` request
    doesn't document a field for "how far back should the granted consent
    let us fetch transactions" (their `access` object only carries
    `valid_until`, the consent's own expiry) -- unlike ACCESS_VALID_DAYS
    above, guessing a field name for this would risk being silently ignored
    by the API at best, or rejected at worst, on a flow that's already
    unverified against a live bank (see this module's honesty note). The
    part of MAX_HISTORICAL_DAYS that's actually actionable from our side --
    how far back the first sync backfills once a link is ACTIVE -- is
    applied in sync.py's `since` calculation instead.
    """
    body = {
        "access": {
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=valid_days)).isoformat(),
        },
        "aspsp": {"name": aspsp_name, "country": aspsp_country},
        "psu_type": "personal",
        "redirect_url": redirect_url,
    }
    return await _request("POST", "/auth", json=body)


async def finalize_session(code: str) -> dict:
    """Exchanges the `code` the bank redirected back with for a session --
    the response includes the list of accounts you now have access to."""
    return await _request("POST", "/sessions", json={"code": code})


async def get_transactions(account_id: str, date_from: str | None = None, continuation_key: str | None = None) -> dict:
    params = {}
    if date_from:
        params["date_from"] = date_from
    if continuation_key:
        params["continuation_key"] = continuation_key
    return await _request("GET", f"/accounts/{account_id}/transactions", params=params)
