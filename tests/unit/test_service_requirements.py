"""
Each image's `requirements.txt` declares everything the code inside that
image needs.

This is the one class of bug the rest of the suite is structurally blind to.
CI installs *every* service's requirements into a single Python environment
(see `.github/workflows/tests.yml`), so a package declared by one service is
importable by all of them. Docker does the opposite: one environment per
image, holding only that image's requirements. A missing line therefore
passes every tier here, green, and crashes the container on startup.

It has now happened twice, with the same package both times:

  * 2026-07-22 -- `python-multipart` missing from `core-networth` and
    `gateway` when file upload (backup restore) was added. Caught by hand,
    running the three services together.
  * 2026-10-04 -- `python-multipart` missing from `bank-sync` when backup
    export/restore was added to it. Not caught: `bank-sync` crash-looped on
    the owner's NAS while `main` was green, the gateway reported the module
    `unreachable`, and bank transaction capture was silently off. FastAPI
    raises at import time, from the `@app.post` decorator, so the service
    never starts and the error names the package.

`python-multipart` is the usual suspect because nothing imports it: FastAPI
needs it at runtime as soon as one endpoint takes `File(...)` or `Form(...)`,
so no import-based check sees it. The two tests below cover both halves --
what the code imports, and what FastAPI needs without an import.

The real fix is to build and start the images in CI (`tests/README.md`,
"Known gaps": the Dockerfiles are not exercised). These tests cost
milliseconds and catch this exact failure in the meantime; they do not
replace it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]

# One entry per Docker image: where its code lives, and the requirements file
# its Dockerfile installs. `shared/` is appended for the images whose
# Dockerfile copies it, since that code runs inside them too.
UNITS = {
    "bank-sync": ("services/bank-sync", "services/bank-sync/requirements.txt"),
    "core-networth": ("services/core-networth", "services/core-networth/requirements.txt"),
    "geo-allocation": ("services/geo-allocation", "services/geo-allocation/requirements.txt"),
    "price-feed": ("services/price-feed", "services/price-feed/requirements.txt"),
    "gateway": ("gateway", "gateway/requirements.txt"),
}

# Import name -> distribution name, for the third-party packages this project
# actually uses. Deliberately a closed list: an import that isn't here is
# either stdlib or local, and guessing would make the test lie in both
# directions.
DISTRIBUTION_OF = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "jwt": "pyjwt",
    "yaml": "pyyaml",
    "openpyxl": "openpyxl",
    "python_calamine": "python-calamine",
    "yfinance": "yfinance",
    "multipart": "python-multipart",
}


def sources(unit: str) -> list[Path]:
    code_dir, _ = UNITS[unit]
    files = sorted((ROOT / code_dir).rglob("*.py"))
    dockerfile = ROOT / code_dir / "Dockerfile"
    if "COPY shared" in dockerfile.read_text():
        files += sorted((ROOT / "shared").rglob("*.py"))
    return files


def declared(unit: str) -> set[str]:
    """The distribution names in the unit's requirements file, normalised the
    way pip does: lowercase, `_`/`.` as `-`, extras and version dropped."""
    _, req = UNITS[unit]
    names = set()
    for line in (ROOT / req).read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[\[<>=!~;]", line)[0].strip()
        names.add(re.sub(r"[-_.]+", "-", name).lower())
    return names


def imported(unit: str) -> set[str]:
    """Top-level module names imported by the unit's code.

    Parsed, not grepped: prose in a docstring ("read from the manifest")
    matches an `import`/`from` regex and produces phantom packages.
    """
    modules = set()
    for path in sources(unit):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def uses_form_data(unit: str) -> bool:
    """Whether any endpoint declares a `File(...)` or `Form(...)` parameter.

    The call is what matters, not the import: `UploadFile` as a bare type
    hint needs nothing extra, while `File(...)` as a default makes FastAPI
    demand python-multipart at import time.
    """
    for path in sources(unit):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {"File", "Form"}):
                return True
    return False


@pytest.mark.parametrize("unit", sorted(UNITS))
def test_every_third_party_import_is_declared(unit):
    missing = {
        DISTRIBUTION_OF[module]
        for module in imported(unit)
        if module in DISTRIBUTION_OF and DISTRIBUTION_OF[module] not in declared(unit)
    }
    assert not missing, (
        f"{unit} imports {', '.join(sorted(missing))} but does not declare it in "
        f"{UNITS[unit][1]}. CI shares one environment between all services, so this "
        f"passes here and fails in the container."
    )


@pytest.mark.parametrize("unit", sorted(UNITS))
def test_form_data_endpoints_declare_python_multipart(unit):
    if not uses_form_data(unit):
        pytest.skip(f"{unit} has no File()/Form() parameter")
    assert "python-multipart" in declared(unit), (
        f"{unit} has an endpoint taking File()/Form() but does not declare "
        f"python-multipart in {UNITS[unit][1]}. FastAPI raises from the route "
        f"decorator, so the service will not start at all."
    )
