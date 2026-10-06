import asyncio
import math
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import Base, engine
from .migrate import run_lightweight_migrations
from .routers import backup, budgets, cash, expenses, networth, portfolios
from .scheduler import scheduler_loop, run_all_jobs

Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fire-and-forget: runs once immediately (price refresh, snapshot
    # catch-up, backup), then keeps re-checking every few hours. Doesn't
    # block startup -- the API is usable immediately either way.
    asyncio.create_task(scheduler_loop())
    yield


app = FastAPI(title="Core Net Worth Service", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # locked down at the gateway layer instead
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolios.router)
app.include_router(cash.router)
app.include_router(expenses.router)
app.include_router(budgets.router)
app.include_router(networth.router)
app.include_router(backup.router)


def _json_safe(value):
    """Replaces any non-finite float with its name, recursively."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)  # "inf", "-inf", "nan"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    """
    FastAPI's own handler, with the offending value made serializable first:
    a validation error echoes the input back, and that input can be a NaN or
    Infinity (Python's json parser accepts them), which JSON can't encode.
    """
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})


@app.post("/scheduler/run-now")
async def trigger_scheduler_now():
    """Manually runs all scheduled jobs immediately, without waiting for the
    next automatic check -- handy for testing or right after adding data."""
    await run_all_jobs()
    return {"status": "done"}


@app.get("/health")
def health():
    return {"status": "ok"}
