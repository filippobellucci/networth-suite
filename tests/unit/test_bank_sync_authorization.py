"""
bank-sync's Authorize -> bank login -> /callback round trip.

The very first real authorization against Enable Banking failed with a 422
before the bank login page even opened: `/auth` requires a `state` field in
its body, and the service was instead smuggling its one-shot token (plus the
link label) as a query string on `redirect_url` -- which also has to match
one of the application's registered redirect URLs exactly. Enable Banking
itself is faked here; what these tests pin is the contract with it: the
token goes in `state`, `redirect_url` is the bare `.../callback`, and the
callback finds its link from the `state` echoed back and nothing else.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from service_loader import service_module

pytestmark = pytest.mark.unit

BANK_LOGIN_URL = "https://bank.example/login"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/import.db")
    main = service_module("bank_app", "main")
    models = service_module("bank_app", "models")
    database = service_module("bank_app", "database")

    engine = create_engine(f"sqlite:///{tmp_path}/bank_sync.db")
    database.Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(main, "SessionLocal", session_factory)
    monkeypatch.setattr(main, "_auth_states", {})

    calls: dict[str, list] = {"auth": [], "sessions": [], "synced": []}

    async def start_authorization(aspsp_name, aspsp_country, redirect_url, valid_days, state):
        calls["auth"].append({"redirect_url": redirect_url, "state": state})
        return {"url": BANK_LOGIN_URL}

    async def finalize_session(code):
        calls["sessions"].append(code)
        return {"session_id": "session-1", "accounts": [{"uid": "account-1"}]}

    async def build_resolver():
        return None

    async def sync_link(db, link, resolver):
        calls["synced"].append(link.label)

    monkeypatch.setattr(main.enable_banking, "start_authorization", start_authorization)
    monkeypatch.setattr(main.enable_banking, "finalize_session", finalize_session)
    monkeypatch.setattr(main, "build_resolver", build_resolver)
    monkeypatch.setattr(main, "sync_link", sync_link)

    with session_factory() as db:
        db.add(models.BankLink(label="Revolut", aspsp_name="Revolut", aspsp_country="IT",
                               portfolio_id="p1", cash_account_id="c1",
                               status=models.LinkStatus.PENDING))
        db.commit()

    from fastapi.testclient import TestClient

    # Not used as a context manager on purpose: that would run the startup
    # hook, which reads links.yaml and starts the background sync loop.
    client = TestClient(main.app, follow_redirects=False)

    def link():
        with session_factory() as db:
            return db.get(models.BankLink, "Revolut")

    return client, calls, link, models, main


def authorize(client, calls) -> str:
    r = client.get("/authorize/Revolut")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == BANK_LOGIN_URL
    return calls["auth"][-1]["state"]


def test_the_token_goes_in_state_and_the_redirect_url_is_the_bare_callback(bank):
    client, calls, link, models, main = bank
    state = authorize(client, calls)

    assert state
    redirect_url = calls["auth"][0]["redirect_url"]
    assert redirect_url == f"{main.PUBLIC_BASE_URL}/callback"
    assert urlsplit(redirect_url).query == ""
    assert link().status == models.LinkStatus.AUTHORIZING


def test_the_callback_finds_its_link_from_the_echoed_state(bank):
    client, calls, link, models, _ = bank
    state = authorize(client, calls)

    r = client.get("/callback", params={"code": "auth-code", "state": state})

    assert r.status_code in (302, 307)
    assert calls["sessions"] == ["auth-code"]
    assert calls["synced"] == ["Revolut"]
    activated = link()
    assert activated.status == models.LinkStatus.ACTIVE
    assert activated.session_id == "session-1"
    assert activated.eb_account_id == "account-1"


def test_a_state_works_only_once(bank):
    client, calls, _, _, _ = bank
    state = authorize(client, calls)

    client.get("/callback", params={"code": "auth-code", "state": state})
    replay = client.get("/callback", params={"code": "auth-code", "state": state})

    assert replay.status_code == 400
    assert calls["sessions"] == ["auth-code"]


@pytest.mark.parametrize("params", [
    {"code": "auth-code"},
    {"code": "auth-code", "state": "not-a-state-we-issued"},
])
def test_a_callback_without_a_state_we_issued_is_refused(bank, params):
    client, calls, link, models, _ = bank
    authorize(client, calls)

    r = client.get("/callback", params=params)

    assert r.status_code == 400
    assert calls["sessions"] == []
    assert link().status == models.LinkStatus.AUTHORIZING


def test_clicking_authorize_again_retires_the_earlier_state(bank):
    client, calls, _, _, _ = bank
    first = authorize(client, calls)
    second = authorize(client, calls)

    assert client.get("/callback", params={"code": "c", "state": first}).status_code == 400
    assert client.get("/callback", params={"code": "c", "state": second}).status_code in (302, 307)


def test_an_expired_state_is_refused(bank, monkeypatch):
    client, calls, _, _, main = bank
    state = authorize(client, calls)
    label, (token, issued_at) = next(iter(main._auth_states.items()))
    main._auth_states[label] = (token, issued_at - main.AUTH_STATE_TTL_SECONDS - 1)

    assert client.get("/callback", params={"code": "c", "state": state}).status_code == 400
    assert calls["sessions"] == []


def test_a_bank_side_error_lands_on_the_link_with_its_description(bank):
    client, calls, link, models, _ = bank
    state = authorize(client, calls)

    client.get("/callback", params={
        "error": "access_denied",
        "error_description": "User cancelled the login",
        "state": state,
    })

    failed = link()
    assert failed.status == models.LinkStatus.ERROR
    assert failed.last_error == "access_denied: User cancelled the login"
    assert calls["sessions"] == []
