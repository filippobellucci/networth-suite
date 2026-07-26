import os
from datetime import datetime

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .registry import MODULES
from . import backup as backup_helpers

app = FastAPI(title="Net Worth Suite - Gateway", version="0.1.0")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Aggregated health check: pings every registered module."""
    results = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, mod in MODULES.items():
            try:
                r = await client.get(f"{mod['base_url']}/health")
                results[name] = "ok" if r.status_code == 200 else f"error ({r.status_code})"
            except httpx.HTTPError:
                results[name] = "unreachable"
    return {"gateway": "ok", "modules": results}


@app.get("/modules")
async def list_modules():
    return {name: mod["description"] for name, mod in MODULES.items()}


# ---------------------------------------------------------------- Aggregated dashboard
# NOTE: declared BEFORE the generic /api/{module}/{path:path} proxy below, since FastAPI
# matches routes in declaration order and the catch-all would otherwise swallow this path.
@app.get("/api/dashboard/summary")
async def dashboard_summary(base_currency: str = "EUR"):
    """
    One call for the frontend's home page: all portfolios + their current
    snapshot + combined net worth history, in a single round trip.
    """
    core = MODULES["core"]["base_url"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        portfolios_resp = await client.get(f"{core}/portfolios")
        portfolios_resp.raise_for_status()
        portfolios = portfolios_resp.json()

        snapshots = []
        for p in portfolios:
            snap_resp = await client.get(f"{core}/portfolios/{p['id']}/snapshot")
            if snap_resp.status_code == 200:
                snapshots.append(snap_resp.json())

        history_resp = await client.get(f"{core}/networth/combined", params={"base_currency": base_currency})
        history = history_resp.json() if history_resp.status_code == 200 else None

    return {
        "portfolios": portfolios,
        "snapshots": snapshots,
        "combined_history": history,
    }


@app.get("/api/dashboard/geo-allocation/{portfolio_id}")
async def portfolio_geo_allocation(portfolio_id: str, category: str | None = None, group_by: str = "country"):
    """
    Combines the core service's current positions (with their EUR value) and
    the geo-allocation service's per-asset country breakdowns into a single
    portfolio-wide geographic exposure, weighted by each position's actual
    current value (not just quantity).

    `category`, if given ("STOCK" or "BOND"), restricts the aggregation
    to only positions whose asset is tagged with that category -- lets
    the frontend show "stocks only" / "bonds only" exposure views.

    `group_by` ("country" default, or "region") controls whether results are
    broken down by individual country or collapsed into five macro-regions.
    """
    core = MODULES["core"]["base_url"]
    geo = MODULES["geo"]["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        snap_resp = await client.get(f"{core}/portfolios/{portfolio_id}/snapshot")
        if snap_resp.status_code != 200:
            raise HTTPException(snap_resp.status_code, "Portfolio not found")
        snapshot = snap_resp.json()

        eligible_positions = snapshot["positions"]
        if category:
            eligible_positions = [
                p for p in eligible_positions if p.get("category") == category
            ]

        assets_payload = {
            "assets": [
                {"asset_id": p["asset_id"], "weight": p["value_base_ccy"]}
                for p in eligible_positions
                if p.get("value_base_ccy")
            ]
        }
        geo_resp = await client.post(
            f"{geo}/allocation/portfolio", json=assets_payload, params={"group_by": group_by}
        )
        geo_result = geo_resp.json() if geo_resp.status_code == 200 else {"regions": [], "covered_weight_pct": 0, "missing_assets": []}

    # attach asset names to the "missing" list so the frontend can prompt uploads with context
    id_to_name = {p["asset_id"]: p["asset_name"] for p in eligible_positions}
    missing_detail = [
        {"asset_id": aid, "asset_name": id_to_name.get(aid, aid)} for aid in geo_result.get("missing_assets", [])
    ]

    return {
        "portfolio_id": portfolio_id,
        "category": category,
        "group_by": group_by,
        "regions": geo_result.get("regions", []),
        "covered_weight_pct": geo_result.get("covered_weight_pct", 0),
        "missing_assets": missing_detail,
    }


# ---------------------------------------------------------------- Cross-service cleanup
# NOTE: declared BEFORE the generic proxy below, same reason as the dashboard
# routes -- FastAPI matches in declaration order and the catch-all would
# otherwise handle this itself (which would skip the geo-allocation cleanup).
@app.delete("/api/core/assets/{asset_id}")
async def delete_asset_and_cleanup(asset_id: str):
    """
    Deleting an asset only ever hit `core-networth` directly, which has no
    knowledge of `geo-allocation`'s per-asset uploaded factsheet (a separate
    microservice, keyed by the same asset_id but with no shared database or
    foreign key to enforce anything). That left an orphaned uploaded file +
    parsed allocation record behind in geo-allocation every time an asset
    with a factsheet was deleted -- harmless (no crash, since geo-allocation
    only looks things up by asset_id and simply won't be asked about a
    deleted one), but genuine leftover private data with no way to clean up
    other than reaching into the container's filesystem by hand.

    Orchestrated here (not in core-networth) because the gateway is the one
    place that already knows about both services; core-networth deleting an
    asset shouldn't need to know geo-allocation exists.
    """
    core = MODULES["core"]["base_url"]
    geo = MODULES["geo"]["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            core_resp = await client.delete(f"{core}/assets/{asset_id}")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Module 'core' unreachable: {e}")

        if core_resp.status_code == 204:
            # Best-effort: a 404 here just means there was never a factsheet
            # uploaded for this asset, which is the common case and not an error.
            try:
                await client.delete(f"{geo}/allocation/assets/{asset_id}")
            except httpx.HTTPError:
                pass  # geo-allocation being unreachable shouldn't block the asset delete that already succeeded

    return Response(status_code=core_resp.status_code, content=core_resp.content)


# ---------------------------------------------------------------- Backup / Restore
# NOTE: declared BEFORE the generic proxy below, same reason as the other
# orchestrated routes above.
@app.get("/api/backup/export")
async def backup_export():
    core = MODULES["core"]["base_url"]
    geo = MODULES["geo"]["base_url"]
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            core_db_resp = await client.get(f"{core}/backup/export")
            core_stats_resp = await client.get(f"{core}/backup/stats")
            geo_zip_resp = await client.get(f"{geo}/backup/export")
            geo_stats_resp = await client.get(f"{geo}/backup/stats")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Could not reach a module while exporting: {e}")

        for label, resp in (("core", core_db_resp), ("geo", geo_zip_resp)):
            if resp.status_code != 200:
                raise HTTPException(502, f"Export failed on module '{label}': {resp.text}")

    combined = backup_helpers.build_combined_zip(
        core_db_resp.content, geo_zip_resp.content,
        core_stats_resp.json() if core_stats_resp.status_code == 200 else {},
        geo_stats_resp.json() if geo_stats_resp.status_code == 200 else {},
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Response(
        content=combined,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="networth-suite-backup-{stamp}.zip"'},
    )


@app.post("/api/backup/preview")
async def backup_preview(file: UploadFile = File(...)):
    """Gateway-only: just reads the manifest already embedded at export
    time, no calls to either backend service needed for this step."""
    data = await file.read()
    try:
        return backup_helpers.read_manifest(data)
    except backup_helpers.InvalidBackupError as e:
        raise HTTPException(400, str(e))


@app.post("/api/backup/restore")
async def backup_restore(file: UploadFile = File(...)):
    core = MODULES["core"]["base_url"]
    geo = MODULES["geo"]["base_url"]
    data = await file.read()

    try:
        core_db_bytes, geo_zip_bytes = backup_helpers.split_combined_zip(data)
    except backup_helpers.InvalidBackupError as e:
        raise HTTPException(400, str(e))

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            core_resp = await client.post(
                f"{core}/backup/restore", files={"file": ("networth.db", core_db_bytes)}
            )
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Module 'core' unreachable during restore: {e}")

        if core_resp.status_code != 200:
            # Nothing in geo-allocation was touched yet, so stop here rather
            # than restoring geo's files against a core database that failed.
            raise HTTPException(core_resp.status_code, f"Restore failed on the main database: {core_resp.text}")

        try:
            geo_resp = await client.post(
                f"{geo}/backup/restore", files={"file": ("fund-files.zip", geo_zip_bytes)}
            )
        except httpx.HTTPError as e:
            raise HTTPException(
                502,
                f"Main database was restored successfully, but the geo-allocation files "
                f"could not be reached: {e}. You may need to retry the restore.",
            )

        if geo_resp.status_code != 200:
            raise HTTPException(
                geo_resp.status_code,
                f"Main database was restored successfully, but restoring the geo-allocation "
                f"files failed: {geo_resp.text}",
            )

    return {"core": core_resp.json(), "geo": geo_resp.json()}


# ---------------------------------------------------------------- Generic reverse proxy
# Catch-all: forwards /api/<module>/<anything> to the matching backend module.
# Kept LAST so specific routes above (like /api/dashboard/summary) take priority.
@app.api_route("/api/{module}/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def proxy(module: str, path: str, request: Request):
    if module not in MODULES:
        raise HTTPException(404, f"Unknown module '{module}'. Available: {list(MODULES.keys())}")

    target = f"{MODULES[module]['base_url']}/{path}"
    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            upstream = await client.request(
                request.method,
                target,
                params=request.query_params,
                content=body,
                headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")},
            )
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Module '{module}' unreachable: {e}")

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
