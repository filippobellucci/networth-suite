"""
Geo Allocation Service
-----------------------
Wraps the `fund_allocation_parser` library (vendored in app/lib) to extract
each fund/ETF's geographic (by-country) allocation from the factsheet Excel
files published by issuers (Amundi, Vanguard, iShares, ...), and to combine
several funds' allocations, weighted by their share of a portfolio, into a
single "portfolio geographic exposure" breakdown.

Every uploaded file is stored locally under DATA_DIR/fund-files/<asset_id>/,
one file per asset -- uploading again replaces the previous one.

Contract:
  POST   /allocation/assets/{asset_id}/upload   (multipart file) -> parse + store
  GET    /allocation/assets/{asset_id}                            -> stored result for one asset
  DELETE /allocation/assets/{asset_id}                            -> remove stored file + data
  GET    /allocation/assets                                       -> stored results for ALL assets
  POST   /allocation/portfolio                                    -> aggregate several assets, weighted
"""
from typing import List

import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from . import storage, backup
from .country_aliases import apply_extra_aliases
from .country_names import display_name
from .regions import REGION_LABELS, region_for
from .lib import parse_bytes
from .lib.exceptions import FundAllocationParserError
from .lib.aggregator import aggregate
from .scheduler import scheduler_loop, run_all_jobs

app = FastAPI(title="Geo Allocation Service", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def _launch_scheduler():
    asyncio.create_task(scheduler_loop())


@app.post("/scheduler/run-now")
async def trigger_scheduler_now():
    await run_all_jobs()
    return {"status": "done"}


apply_extra_aliases()


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- Backup / Restore
@app.get("/backup/export")
def backup_export():
    data = backup.export_zip_bytes()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="fund-files.zip"'},
    )


@app.get("/backup/stats")
def backup_stats():
    return backup.get_stats()


@app.post("/backup/preview")
async def backup_preview(file: UploadFile = File(...)):
    try:
        return backup.preview_uploaded_zip(await file.read())
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))


@app.post("/backup/restore")
async def backup_restore(file: UploadFile = File(...)):
    try:
        return backup.restore_from_zip(await file.read())
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- Per-asset upload / retrieval
@app.post("/allocation/assets/{asset_id}/upload")
async def upload_allocation_file(asset_id: str, file: UploadFile = File(...)):
    content = await file.read()
    try:
        result = parse_bytes(content, source_file=file.filename)
    except FundAllocationParserError as e:
        raise HTTPException(422, f"Could not parse file '{file.filename}': {e}")

    if result.total_weight() < 0.5:
        # Parsed "something" but coverage is too low to be trustworthy -- surface it
        # rather than silently storing a near-empty breakdown.
        raise HTTPException(
            422,
            f"The file was read but only covers {result.total_weight()*100:.1f}% of the fund: "
            "check that this is the correct factsheet.",
        )

    record = storage.save_upload(asset_id, file.filename, content, result)
    return record


@app.get("/allocation/assets/{asset_id}")
def get_asset_allocation(asset_id: str):
    record = storage.load(asset_id)
    if not record:
        raise HTTPException(404, "No allocation file uploaded for this asset")
    return record


@app.get("/allocation/assets")
def list_asset_allocations():
    return storage.list_all()


@app.delete("/allocation/assets/{asset_id}", status_code=204)
def delete_asset_allocation(asset_id: str):
    if not storage.delete(asset_id):
        raise HTTPException(404, "No allocation file uploaded for this asset")


# ---------------------------------------------------------------- Portfolio-level aggregation
class PortfolioAssetWeight(BaseModel):
    asset_id: str
    weight: float  # this asset's share of the portfolio; any positive scale, normalized internally


class PortfolioAllocationRequest(BaseModel):
    assets: List[PortfolioAssetWeight]


class RegionWeight(BaseModel):
    country: str
    country_name: str
    weight_pct: float


class PortfolioAllocationResponse(BaseModel):
    regions: List[RegionWeight]
    covered_weight_pct: float  # share of the portfolio for which allocation data was available
    missing_assets: List[str]  # asset_ids with no allocation file uploaded, excluded from the result


@app.post("/allocation/portfolio", response_model=PortfolioAllocationResponse)
def aggregate_portfolio_allocation(payload: PortfolioAllocationRequest, group_by: str = "country"):
    """
    `group_by="country"` (default) returns one row per ISO2 country code.
    `group_by="region"` collapses those into five macro-regions (Americas,
    Europe, Asia, Africa, Oceania) instead -- same response shape, `country`
    holds the region code and `country_name` the region label.
    """
    results = []
    weights = []
    missing = []
    total_requested = sum(a.weight for a in payload.assets) or 1.0

    for a in payload.assets:
        record = storage.load(a.asset_id)
        if not record:
            missing.append(a.asset_id)
            continue
        from .lib.models import AllocationResult, FundMetadata
        r = record["result"]
        results.append(AllocationResult(weights=r["weights"], metadata=FundMetadata(**r["metadata"])))
        weights.append(a.weight)

    covered_pct = round(100 * sum(weights) / total_requested, 2) if total_requested else 0.0

    if not results:
        return PortfolioAllocationResponse(regions=[], covered_weight_pct=0.0, missing_assets=missing)

    combined = aggregate(results, fund_weights=weights, normalize=True)

    if group_by == "region":
        by_region: dict[str, float] = {}
        for code, w in combined.items():
            region = region_for(code)
            by_region[region] = by_region.get(region, 0.0) + w
        regions = [
            RegionWeight(country=code, country_name=REGION_LABELS.get(code, code), weight_pct=round(w * 100, 3))
            for code, w in sorted(by_region.items(), key=lambda kv: -kv[1])
        ]
    else:
        regions = [
            RegionWeight(country=code, country_name=display_name(code), weight_pct=round(w * 100, 3))
            for code, w in sorted(combined.items(), key=lambda kv: -kv[1])
        ]

    return PortfolioAllocationResponse(regions=regions, covered_weight_pct=covered_pct, missing_assets=missing)
