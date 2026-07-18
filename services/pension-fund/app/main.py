"""
Pension Fund Service
----------------------
Replicates the "Analisi Fondo Pensione (COMETA)" sheet: given contribution
history and comparto (fund line) performance, projects value over time.

This is a starting implementation with a simple compounding model;
extend `project_pension_value()` with the exact COMETA rules (comparto
returns, TFR vs voluntary contribution split, employer match, etc.)
whenever you're ready to port that sheet's formulas over.
"""
from datetime import date
from typing import List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Pension Fund Service", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ContributionEntry(BaseModel):
    entry_date: date
    employee_contribution: float
    employer_contribution: float
    severance_contribution: float


class ProjectionRequest(BaseModel):
    contributions: List[ContributionEntry]
    annual_return_pct: float = 3.0  # comparto's assumed annual return
    projection_years: int = 10


class ProjectionPoint(BaseModel):
    year: int
    balance: float


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/pension/projection", response_model=List[ProjectionPoint])
def project_pension_value(req: ProjectionRequest):
    current_balance = sum(
        c.employee_contribution + c.employer_contribution + c.severance_contribution
        for c in req.contributions
    )
    annual_contribution = 0.0
    if req.contributions:
        # naive estimate: average of the last 12 entries treated as monthly contributions
        recent = req.contributions[-12:]
        annual_contribution = sum(
            c.employee_contribution + c.employer_contribution + c.severance_contribution for c in recent
        ) * (12 / len(recent))

    r = req.annual_return_pct / 100.0
    points = [ProjectionPoint(year=0, balance=round(current_balance, 2))]
    balance = current_balance
    for y in range(1, req.projection_years + 1):
        balance = balance * (1 + r) + annual_contribution
        points.append(ProjectionPoint(year=y, balance=round(balance, 2)))
    return points
