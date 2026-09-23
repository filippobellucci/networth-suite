"""
The archive handling on both ends of backup/restore.

A restore takes a file the user supplies and writes it into the running
instance, which makes it the only place in this app where untrusted bytes
reach the filesystem. The guards below are what stands between the two, and
each one is here because the unguarded version was a real finding:

  * an entry named "../../x" escaping the destination directory;
  * a small archive declaring an enormous expansion, or lying about it and
    expanding as it is written;
  * a corrupt member turning a bad upload into a 500;
  * a member named to look like a sibling of the destination ("/data/x-evil"
    next to "/data/x"), which a plain startswith() check lets through.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from service_loader import service_module

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def geo_backup(tmp_path_factory, monkeypatch_session=None):
    import os

    os.environ.setdefault("DATA_DIR", str(tmp_path_factory.mktemp("geo-backup")))
    return service_module("geo_app", "backup")


@pytest.fixture(scope="module")
def gw_backup():
    return service_module("gw_app", "backup")


def zip_of(entries: dict[str, bytes], compress=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ------------------------------------------------------------------ zip slip
@pytest.mark.parametrize(
    "name",
    [
        "../escaped.txt",
        "../../escaped.txt",
        "a/../../escaped.txt",
        "/absolute/escaped.txt",
        "./../escaped.txt",
    ],
)
def test_an_entry_that_escapes_the_destination_is_refused(geo_backup, tmp_path, name):
    with pytest.raises(geo_backup.InvalidBackupError):
        geo_backup._safe_target(tmp_path, name)


def test_a_sibling_lookalike_is_refused(geo_backup, tmp_path):
    """"/data/fund-files-evil" starts with "/data/fund-files" as a string
    but is not inside it. A startswith() check on the path text lets this
    through; a real path comparison does not."""
    base = tmp_path / "fund-files"
    base.mkdir()
    with pytest.raises(geo_backup.InvalidBackupError):
        geo_backup._safe_target(base, "../fund-files-evil/x.txt")


@pytest.mark.parametrize("name", ["asset1/source.xlsx", "asset1/allocation.json", "plain.txt"])
def test_an_ordinary_entry_is_allowed(geo_backup, tmp_path, name):
    target = geo_backup._safe_target(tmp_path, name)
    assert str(target).startswith(str(tmp_path))


# ------------------------------------------------------------------ zip bomb
def test_an_archive_declaring_a_huge_expansion_is_refused(geo_backup, monkeypatch):
    """Cheap pre-check on the declared sizes, before a byte is written.

    The ceiling is lowered for the test rather than building a real 1GB
    expansion: what is being checked is that the guard fires on "declares
    more than the limit", and allocating a gigabyte of zeros to prove it
    would make the unit suite too slow to run on every save.
    """
    monkeypatch.setattr(geo_backup, "MAX_BACKUP_EXTRACTED_SIZE_BYTES", 2 * 1024 * 1024)
    bomb = zip_of({f"asset{i}/big.bin": b"\0" * (1024 * 1024) for i in range(4)})
    assert len(bomb) < 100 * 1024, "the archive itself must stay small to be a bomb"
    with pytest.raises(geo_backup.InvalidBackupError) as exc:
        geo_backup.restore_from_zip(bomb)
    assert "limit" in str(exc.value).lower()


def test_the_default_ceiling_is_the_documented_one(geo_backup):
    """The test above lowers the limit, so this pins what it really is."""
    assert geo_backup.MAX_BACKUP_EXTRACTED_SIZE_BYTES == 1024 * 1024 * 1024


def test_a_modest_archive_is_not_mistaken_for_a_bomb(geo_backup):
    ok = zip_of({"asset1/allocation.json": json.dumps({"asset_id": "asset1"}).encode()})
    result = geo_backup.restore_from_zip(ok)
    assert isinstance(result, dict)


def test_a_corrupt_member_is_a_bad_request_not_a_crash(geo_backup):
    raw = bytearray(zip_of({"asset1/allocation.json": b"{}" * 500}))
    # corrupt the compressed payload while leaving the directory intact
    raw[len(raw) // 3] ^= 0xFF
    raw[len(raw) // 3 + 1] ^= 0xFF
    with pytest.raises(geo_backup.InvalidBackupError):
        geo_backup.restore_from_zip(bytes(raw))


def test_something_that_is_not_a_zip_at_all(geo_backup):
    with pytest.raises(geo_backup.InvalidBackupError):
        geo_backup.restore_from_zip(b"this is definitely not a zip archive")


# ---------------------------------------------------- the combined gateway zip
def test_a_combined_backup_round_trips_through_its_own_helpers(gw_backup):
    core_db = b"SQLite format 3\x00" + b"pretend database"
    geo_zip = zip_of({"asset1/allocation.json": b"{}"})
    combined = gw_backup.build_combined_zip(core_db, geo_zip,
                                            {"portfolios": 2}, {"assets_with_files": 1})
    manifest = gw_backup.read_manifest(combined)
    assert manifest["app"] == "networth-suite"
    assert manifest["core"]["portfolios"] == 2
    assert manifest["geo"]["assets_with_files"] == 1
    assert "exported_at" in manifest

    back_core, back_geo = gw_backup.split_combined_zip(combined)
    assert back_core == core_db
    assert back_geo == geo_zip


def test_an_unrelated_zip_is_not_accepted_as_a_backup(gw_backup):
    with pytest.raises(gw_backup.InvalidBackupError):
        gw_backup.read_manifest(zip_of({"random.txt": b"hello"}))


def test_a_backup_with_an_unreadable_manifest_is_refused(gw_backup):
    with pytest.raises(gw_backup.InvalidBackupError):
        gw_backup.read_manifest(zip_of({"manifest.json": b"{not json"}))


def test_a_file_that_is_not_a_zip_is_refused(gw_backup):
    with pytest.raises(gw_backup.InvalidBackupError):
        gw_backup.read_manifest(b"nope")
    with pytest.raises(gw_backup.InvalidBackupError):
        gw_backup.split_combined_zip(b"nope")


def test_a_backup_missing_one_of_its_two_halves_is_refused(gw_backup):
    partial = zip_of({
        "manifest.json": json.dumps({"app": "networth-suite", "core": {}, "geo": {}}).encode(),
        "core/networth.db": b"SQLite format 3\x00",
    })
    with pytest.raises(gw_backup.InvalidBackupError):
        gw_backup.split_combined_zip(partial)
