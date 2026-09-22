"""
Where backups are written when the configured folder is not usable.

Found by this suite's very first CI run, in a deployment mode the README
documents and nothing had ever exercised: `/backups` was hardcoded, and it
sits at the filesystem root, which only root can create. Under Docker it is
a bind-mounted volume and everything works; running the services directly on
the host it fails, and it failed twice over --

  * Settings -> Restore raised PermissionError out of the endpoint, so the
    user got a bare "Internal Server Error" with nothing to act on;
  * the daily backup job caught its own exception and logged a warning, so
    it simply never ran. That is the worse of the two: the user believes
    they have automatic backups and has none.

A backup written somewhere unexpected is worth incomparably more than no
backup, so an unusable directory falls back to one under DATA_DIR and says
where it went.

Note how "unusable" is arranged below. Making a directory read-only proves
nothing when the tests run as root, because root ignores the permission bits
-- which is precisely why this bug survived every local run and only
appeared on a CI runner. Putting a plain FILE where a parent directory
should be fails identically for every user, so these tests mean the same
thing wherever they run.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from service_loader import service_module

pytestmark = pytest.mark.unit

SERVICES = ["core_app", "geo_app"]


@pytest.fixture(params=SERVICES, ids=SERVICES)
def config(request, tmp_path):
    os.environ.setdefault("DATA_DIR", str(tmp_path))
    return service_module(request.param, "config")


def unusable_path(tmp_path: Path) -> Path:
    """A path that cannot be created, for root and for anyone else: its
    parent is a regular file."""
    blocker = tmp_path / "a-file-not-a-directory"
    blocker.write_text("")
    return blocker / "backups"


def test_the_configured_directory_is_used_when_it_works(config, tmp_path, monkeypatch):
    chosen = tmp_path / "backups-here"
    monkeypatch.setattr(config, "BACKUP_DIR", chosen)
    target = config.backup_target("2026-06-15")
    assert target == chosen / "2026-06-15"
    assert target.is_dir()


def test_an_unusable_directory_falls_back_instead_of_raising(config, tmp_path, monkeypatch):
    """This is the exact CI failure: an OSError escaping to the caller, which
    reached the user as a bare 500."""
    monkeypatch.setattr(config, "BACKUP_DIR", unusable_path(tmp_path))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")

    target = config.backup_target("2026-06-15")

    assert target.is_dir(), "a fallback must actually exist, not just be named"
    assert tmp_path / "data" in target.parents
    assert target.name == "2026-06-15"


def test_the_fallback_is_writable(config, tmp_path, monkeypatch):
    """Returning a path that cannot be written to would only move the failure
    one line further down."""
    monkeypatch.setattr(config, "BACKUP_DIR", unusable_path(tmp_path))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")

    probe = config.backup_target("2026-06-15") / "networth.db"
    probe.write_bytes(b"x")
    assert probe.read_bytes() == b"x"


def test_the_fallback_is_announced(config, tmp_path, monkeypatch, caplog):
    """Silently writing somewhere else would be its own bug: the whole point
    of a backup is knowing where it is."""
    monkeypatch.setattr(config, "BACKUP_DIR", unusable_path(tmp_path))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")

    with caplog.at_level("WARNING"):
        target = config.backup_target("2026-06-15")

    assert caplog.records, "the substitution must be logged"
    assert str(target) in caplog.text
    assert "BACKUP_DIR" in caplog.text, "and it must say which setting to change"


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root ignores permission bits -- which is how this bug hid")
def test_a_read_only_directory_also_falls_back(config, tmp_path, monkeypatch):
    """The shape the CI runner actually hit: the parent exists but belongs to
    somebody else."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setattr(config, "BACKUP_DIR", locked / "backups")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    try:
        target = config.backup_target("2026-06-15")
    finally:
        locked.chmod(0o700)
    assert tmp_path / "data" in target.parents


def test_the_default_is_still_the_docker_mount(config):
    """docker-compose bind-mounts ./backups/<service> to /backups, so the
    default cannot move without changing that too."""
    assert Path(os.environ.get("BACKUP_DIR", "/backups")) == Path("/backups")


def test_the_directory_is_configurable(config, tmp_path, monkeypatch):
    """The fallback is a safety net, not the mechanism. Someone running
    outside Docker should be able to just say where backups go."""
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "chosen"))
    import importlib

    reloaded = importlib.reload(config)
    assert reloaded.BACKUP_DIR == tmp_path / "chosen"
    assert reloaded.backup_target("2026-06-15").is_dir()
