"""
Guards the one invariant a Dockerfile `COPY` and docker-compose.yml's build
`context` have to agree on: a `COPY` can only reach paths inside its own
context, never above it.

core-networth, geo-allocation and bank-sync `COPY shared/` (backup
rotation), one level above their own folder, so their compose context had to
become the repository root -- see DESIGN_NOTES.md,
`shared/backup_retention.py`. A live deploy still built from a per-service
context on 2026-10-04 (a hand-written remote-context file, outside this
repository, following README.md's table) and failed with a misleading
`COPY shared ./shared` error. Nothing here ever read a Dockerfile or
docker-compose.yml, so nothing caught the table going stale.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

_COPY_LINE = re.compile(r"^COPY\s+(.+?)\s+(\S+)\s*$")


def _compose_build_specs() -> dict[str, tuple[Path, Path]]:
    """service name -> (build context, dockerfile path), both repo-relative."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    specs = {}
    for name, service in compose["services"].items():
        build = service.get("build")
        if build is None:
            continue
        if isinstance(build, str):
            context = Path(build)
            dockerfile = context / "Dockerfile"
        else:
            context = Path(build["context"])
            # Compose resolves a relative `dockerfile:` from the context, not from the
            # repository root -- https://docs.docker.com/reference/compose-file/build/.
            dockerfile = context / build.get("dockerfile", "Dockerfile")
        specs[name] = (context, dockerfile)
    return specs


def _readme_build_table() -> dict[str, tuple[Path, Path]]:
    """Same shape, parsed from README.md's "Building straight from GitHub" table."""
    readme = (REPO_ROOT / "README.md").read_text()
    section = readme.split("Building straight from GitHub, without a clone", 1)[1]

    table_lines = []
    started = False
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            started = True
            table_lines.append(stripped)
        elif started:
            break  # the blank line right after the table

    rows = {}
    for line in table_lines[2:]:  # skip the header and the --- separator
        cells = [c.strip() for c in line.strip("|").split("|")]
        name = cells[0].strip("`")
        context = Path(".") if cells[1] == "repository root" else Path(cells[1].strip("`"))
        dockerfile = context / "Dockerfile" if cells[2] == "default" else Path(cells[2].strip("`"))
        rows[name] = (context, dockerfile)
    return rows


def _copy_sources(dockerfile: Path) -> list[str]:
    """Every host-side path a `COPY` instruction reads, in build order.

    Skips `COPY --from=<stage>`: that copies between build stages, not from
    the host, so it has no context path to check.
    """
    sources = []
    for line in dockerfile.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("COPY ") or "--from=" in stripped:
            continue
        match = _COPY_LINE.match(stripped)
        assert match, f"{dockerfile}: can't parse `{stripped}`"
        srcs, _dest = match.groups()
        sources.extend(srcs.split())
    return sources


_SPECS = _compose_build_specs()


def test_compose_contexts_match_readme_table():
    readme_specs = _readme_build_table()
    assert set(_SPECS) == set(readme_specs), (
        "docker-compose.yml and README.md's \"Building straight from GitHub\" table list a "
        f"different set of services: compose has {sorted(_SPECS)}, README has "
        f"{sorted(readme_specs)}"
    )
    for name, spec in _SPECS.items():
        assert spec == readme_specs[name], (
            f"{name}: docker-compose.yml declares build context={spec[0]} dockerfile={spec[1]}, "
            f"but README.md's table says context={readme_specs[name][0]} "
            f"dockerfile={readme_specs[name][1]} -- update the table to match, or fix whichever "
            "one is wrong"
        )


@pytest.mark.parametrize("name", sorted(_SPECS))
def test_dockerfile_copy_paths_resolve_within_declared_context(name):
    context, dockerfile = _SPECS[name]
    for src in _copy_sources(REPO_ROOT / dockerfile):
        if "*" in src:
            assert list((REPO_ROOT / context).glob(src)), (
                f"{dockerfile}: `COPY {src}` matches nothing under build context {context} "
                f"(docker-compose.yml) -- a context this narrow can't see what the Dockerfile "
                "is trying to copy"
            )
        else:
            target = REPO_ROOT / context / src
            assert target.exists(), (
                f"{dockerfile}: `COPY {src}` does not exist under build context {context} "
                f"(resolved to {target}) -- docker-compose.yml's build context for {name!r} is "
                "too narrow for this Dockerfile's COPY paths, or the COPY path is wrong"
            )
