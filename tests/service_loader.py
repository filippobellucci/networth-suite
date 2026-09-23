"""
Imports a service's `app` package under a unique alias.

Every service in this repo names its package `app` (services/core-networth/app,
services/geo-allocation/app, gateway/app, ...). Putting each service's root on
sys.path and importing `app` therefore works for exactly one of them per
process: the second import finds the first one already in sys.modules and the
tests silently run against the wrong service.

Loading by file location with an explicit alias avoids that. Because every
service imports its own modules relatively (`from . import models`), the
package works unchanged under any name -- so core-networth becomes `core_app`,
geo-allocation `geo_app`, and both can be inspected in the same test run.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent

SERVICE_ROOTS = {
    "core_app": REPO_ROOT / "services" / "core-networth",
    "geo_app": REPO_ROOT / "services" / "geo-allocation",
    "price_app": REPO_ROOT / "services" / "price-feed",
    "bank_app": REPO_ROOT / "services" / "bank-sync",
    "gw_app": REPO_ROOT / "gateway",
}


def load_service(alias: str) -> ModuleType:
    """Imports (once) the service package registered under `alias`."""
    if alias in sys.modules:
        return sys.modules[alias]
    if alias not in SERVICE_ROOTS:
        raise KeyError(f"Unknown service alias {alias!r}; known: {sorted(SERVICE_ROOTS)}")

    root = SERVICE_ROOTS[alias]
    spec = importlib.util.spec_from_file_location(
        alias,
        root / "app" / "__init__.py",
        submodule_search_locations=[str(root / "app")],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery
        raise ImportError(f"Could not build a spec for {alias} at {root}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def service_module(alias: str, name: str) -> ModuleType:
    """`service_module("core_app", "valuation")` -> the valuation module."""
    load_service(alias)
    return importlib.import_module(f"{alias}.{name}")
