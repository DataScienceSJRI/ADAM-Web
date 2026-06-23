from typing import Literal

from pydantic import BaseModel


class FoodObject(BaseModel):
    id: str
    description: str
    visual_context: str
    search_terms: list[str]  # 3-5 terms, specificity gradient


class PlateContext(BaseModel):
    container_type: str | None
    estimated_diameter_cm: float | None
    reference_objects: list[str]
    fill_level_pct: float | None


class SceneAnalysis(BaseModel):  # Phase 1 output
    foods: list[FoodObject]
    plate_context: PlateContext


class MatchCandidate(BaseModel):  # one ADS RecipeSearchResult, carried through
    recipe_code: str
    recipe_name: str | None
    recipe_category: str | None
    recipe_description: str | None
    recipe_weight_g: float | None
    energy_kcal: float | None
    portion: float | None


class MatchDecision(BaseModel):  # Phase 3 output, one per food
    food_id: str
    status: Literal["accepted", "accepted_flagged", "unidentified", "not_found"]
    matched: MatchCandidate | None
    match_confidence: float  # 0.0-1.0
    reasoning: str
    candidates_considered: list[MatchCandidate]  # top-3 even if not matched


class QuantityEstimate(BaseModel):  # Phase 4 output, one per matched food
    food_id: str
    quantity_g: float
    quantity_g_min: float
    quantity_g_max: float
    serving_multiplier: float | None  # vs recipe_weight_g, when available
    quantity_confidence: Literal["high", "medium", "low"]
    quantity_method: Literal["serving_multiplier", "category_prior_fallback"]
    estimation_reasoning: str


class FoodResult(BaseModel):  # final per-food record
    food_id: str
    match: MatchDecision
    quantity: QuantityEstimate | None  # null if status != accepted*


class PipelineOutput(BaseModel):  # the whole tool's return value
    analysis_id: str
    foods: list[FoodResult]
    plate_context: PlateContext
    flags: list[str]
