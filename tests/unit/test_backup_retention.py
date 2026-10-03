"""
The rotation rule applied to every service's daily backup folder: keep every
day from the last month, then thin older entries down to one per calendar
month -- and never remove the newest entry, however the retention setting is
misconfigured. Before this existed, nothing in any of the three `backup.py`
files ever deleted a daily `YYYY-MM-DD` or `pre-restore-<timestamp>` folder,
so `./backups/` only ever grew (AGE-2).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.backup_retention import rotate_backups

pytestmark = pytest.mark.unit


def make(base: Path, *names: str) -> None:
    for name in names:
        (base / name).mkdir()


def remaining(base: Path) -> set[str]:
    return {p.name for p in base.iterdir()}


def test_everything_within_the_window_survives(tmp_path):
    make(tmp_path, "2026-09-05", "2026-09-10", "2026-09-20", "2026-10-03")
    rotate_backups(tmp_path, retention_days=30)
    assert remaining(tmp_path) == {"2026-09-05", "2026-09-10", "2026-09-20", "2026-10-03"}


def test_older_entries_thin_to_one_per_month(tmp_path):
    # Three different months, well before the 30-day window, plus one recent
    # entry that anchors "now". Each older month should keep only its own
    # latest day.
    make(
        tmp_path,
        "2026-01-03", "2026-01-15", "2026-01-28",   # January -> keep 28
        "2026-02-02", "2026-02-20",                 # February -> keep 20
        "2026-03-01",                                # March -> keep 1 (alone)
        "2026-10-03",                                 # the newest, anchors "now"
    )
    removed = rotate_backups(tmp_path, retention_days=30)

    assert remaining(tmp_path) == {"2026-01-28", "2026-02-20", "2026-03-01", "2026-10-03"}
    assert {p.name for p in removed} == {"2026-01-03", "2026-01-15", "2026-02-02"}


def test_pre_restore_copies_rotate_alongside_daily_ones(tmp_path):
    """pre-restore-<timestamp> safety copies are the worst case (one per
    restore) and must be thinned exactly like daily ones, not pile up
    forever."""
    make(
        tmp_path,
        "2026-01-10",
        "pre-restore-2026-01-10T08-00-00",
        "pre-restore-2026-01-10T09-30-00",
        "2026-10-03",
    )
    rotate_backups(tmp_path, retention_days=30)

    # Only the latest January entry (the 09:30 safety copy) plus the newest.
    assert remaining(tmp_path) == {"pre-restore-2026-01-10T09-30-00", "2026-10-03"}


@pytest.mark.parametrize("retention_days", [0, -5, -9999])
def test_the_newest_entry_always_survives_even_with_an_absurd_setting(tmp_path, retention_days):
    make(tmp_path, "2026-08-01", "2026-09-15", "2026-10-03")
    rotate_backups(tmp_path, retention_days=retention_days)
    assert "2026-10-03" in remaining(tmp_path)


def test_a_single_entry_is_left_alone(tmp_path):
    make(tmp_path, "2026-10-03")
    assert rotate_backups(tmp_path, retention_days=30) == []
    assert remaining(tmp_path) == {"2026-10-03"}


def test_unrecognized_entries_are_never_touched(tmp_path):
    """Something that isn't one of our folder names (a stray file, a typo'd
    directory) is left exactly as it was -- rotation must never guess."""
    (tmp_path / "notes.txt").write_text("hello")
    make(tmp_path, "some-other-folder", "2026-10-03")
    rotate_backups(tmp_path, retention_days=0)
    assert (tmp_path / "notes.txt").exists()
    assert (tmp_path / "some-other-folder").is_dir()


def test_a_missing_directory_is_a_no_op(tmp_path):
    assert rotate_backups(tmp_path / "does-not-exist", retention_days=30) == []
