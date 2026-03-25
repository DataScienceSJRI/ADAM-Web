from pydantic import BaseModel
from typing import Optional


class GeneratePlanRequest(BaseModel):
    week_no: int = 1
    onboarding_id: Optional[str] = None


class GeneratePlanResponse(BaseModel):
    status: str
    rows_written: int
    plan_id: Optional[str] = None
    onboarding_id: Optional[str] = None
    optimization_status: Optional[str] = None
    message: Optional[str] = None


class PlanSummary(BaseModel):
    plan_id: str
    onboarding_id: Optional[str] = None
    week_no: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    row_count: int


class PlanStatusResponse(BaseModel):
    has_plan: bool
    row_count: int
    plans: list[PlanSummary]
