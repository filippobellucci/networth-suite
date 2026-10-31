"""
The SMTP alert channel (AGE-11): a plain email, off unless SMTP_HOST is
set, so the app behaves exactly as it does today -- no outbound
connection, nothing in the logs -- for anyone who never configures it.

A fake smtplib.SMTP stands in for a real mail server; nothing here opens a
socket.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        self.raise_on_connect = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        if self.raise_on_connect:
            raise OSError("connection refused")
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


class FakeSMTPSSL(FakeSMTP):
    """smtplib.SMTP_SSL: the connection is TLS from the first byte, so
    STARTTLS on top of it is a protocol error."""

    def starttls(self):
        raise AssertionError("STARTTLS on an implicit-TLS connection")


@pytest.fixture
def notify(monkeypatch):
    FakeSMTP.instances.clear()
    import shared.notify as notify_module

    monkeypatch.setattr(notify_module, "SMTP_HOST", "")
    monkeypatch.setattr(notify_module, "SMTP_FROM", "")
    monkeypatch.setattr(notify_module, "SMTP_TO", "")
    monkeypatch.setattr(notify_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", FakeSMTPSSL)
    return notify_module


def configure(notify, monkeypatch, **overrides):
    values = {
        "SMTP_HOST": "mail.example.com",
        "SMTP_PORT": 587,
        "SMTP_USERNAME": "",
        "SMTP_PASSWORD": "",
        "SMTP_FROM": "networth@example.com",
        "SMTP_TO": "owner@example.com",
        "SMTP_USE_TLS": True,
        "SMTP_USE_SSL": False,
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setattr(notify, name, value)


def test_disabled_by_default_sends_nothing_and_opens_no_connection(notify):
    assert notify.SMTP_HOST == ""
    assert notify.enabled() is False
    assert notify.send("subject", "body") is False
    assert FakeSMTP.instances == []


def test_enabled_sends_one_message_with_starttls_and_login(notify, monkeypatch):
    configure(notify, monkeypatch, SMTP_USERNAME="bot", SMTP_PASSWORD="secret")
    assert notify.send("Budget exceeded", "the Groceries budget is over") is True
    (server,) = FakeSMTP.instances
    assert type(server) is FakeSMTP
    assert server.started_tls is True
    assert server.logged_in == ("bot", "secret")
    (msg,) = server.sent
    assert msg["Subject"] == "Budget exceeded"
    assert msg["From"] == "networth@example.com"
    assert msg["To"] == "owner@example.com"


def test_a_mail_server_failure_is_swallowed_and_reported_as_not_sent(notify, monkeypatch):
    configure(notify, monkeypatch)

    def boom(*a, **kw):
        server = FakeSMTP(*a, **kw)
        server.raise_on_connect = True
        return server

    monkeypatch.setattr(notify.smtplib, "SMTP", boom)
    assert notify.send("subject", "body") is False


def test_missing_recipient_also_disables_the_channel(notify, monkeypatch):
    configure(notify, monkeypatch, SMTP_TO="")
    assert notify.enabled() is False
    assert notify.send("subject", "body") is False
    assert FakeSMTP.instances == []


async def test_send_async_returns_what_send_returns_off_the_event_loop(notify, monkeypatch):
    import threading

    configure(notify, monkeypatch)
    loop_thread = threading.get_ident()
    sending_threads = []
    real_send = notify.send

    def recording_send(subject, body):
        sending_threads.append(threading.get_ident())
        return real_send(subject, body)

    monkeypatch.setattr(notify, "send", recording_send)
    assert await notify.send_async("Budget exceeded", "body") is True
    (server,) = FakeSMTP.instances
    (msg,) = server.sent
    assert msg["Subject"] == "Budget exceeded"
    assert sending_threads and sending_threads[0] != loop_thread


async def test_send_async_with_the_channel_off_opens_no_connection(notify):
    assert await notify.send_async("subject", "body") is False
    assert FakeSMTP.instances == []


def test_smtps_uses_implicit_tls_and_ignores_starttls(notify, monkeypatch):
    configure(notify, monkeypatch, SMTP_PORT=465, SMTP_USE_SSL=True, SMTP_USE_TLS=True,
              SMTP_USERNAME="bot", SMTP_PASSWORD="secret")
    assert notify.send("Budget exceeded", "body") is True
    (server,) = FakeSMTP.instances
    assert type(server) is FakeSMTPSSL
    assert (server.host, server.port) == ("mail.example.com", 465)
    assert server.logged_in == ("bot", "secret")
    (msg,) = server.sent
    assert msg["Subject"] == "Budget exceeded"


def test_smtps_is_off_by_default(monkeypatch):
    import importlib

    import shared.notify as notify_module

    monkeypatch.delenv("SMTP_USE_SSL", raising=False)
    assert importlib.reload(notify_module).SMTP_USE_SSL is False
