from food_id_agent.ads_client import ADSClient, RecipeSearchResult
from food_id_agent.pipeline.phase2_search import search_candidates
from food_id_agent.schemas import FoodObject, MatchCandidate, MatchDecision
from food_id_agent.vlm.base import VLMClient

ACCEPT_THRESHOLD = 0.75
FLAG_THRESHOLD = 0.45
MAX_BROADEN_ITERATIONS = 2

MATCH_DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "recipe_code": {"type": ["string", "null"]},
        "match_confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "broadened_search_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "recipe_code",
        "match_confidence",
        "reasoning",
        "broadened_search_terms",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a recipe-matching assistant. Given a photographed food item and "
    "a pool of candidate recipes, pick the best matching recipe_code (or null "
    "if none plausibly match) and a confidence score in [0, 1]."
)


def _to_candidate(recipe: RecipeSearchResult) -> MatchCandidate:
    return MatchCandidate(
        recipe_code=recipe.recipeCode,
        recipe_name=recipe.recipeName,
        recipe_category=recipe.recipeCategory,
        recipe_description=recipe.Recipe_Description,
        recipe_weight_g=recipe.recipeWeightG,
        energy_kcal=recipe.Energy_Kcal,
        portion=recipe.Portion,
    )


def _candidate_pool_prompt(food: FoodObject, candidates: list[MatchCandidate]) -> str:
    lines = [
        f"Food item: {food.description} (context: {food.visual_context})",
        "Candidate recipes:",
    ]
    for c in candidates:
        lines.append(
            f"- code={c.recipe_code} name={c.recipe_name!r} "
            f"category={c.recipe_category!r} description={c.recipe_description!r}"
        )
    lines.append(
        "Score on name match, category plausibility, description plausibility, "
        "and contextual plausibility. If no candidate plausibly matches, return "
        "recipe_code=null and suggest broadened_search_terms (more generic, "
        "stripped of regional specifics)."
    )
    return "\n".join(lines)


async def _decide_one(
    vlm_client: VLMClient,
    image_bytes: bytes,
    food: FoodObject,
    candidates: list[MatchCandidate],
) -> dict:
    raw = await vlm_client.complete_structured(
        image_bytes=image_bytes,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_candidate_pool_prompt(food, candidates),
        json_schema=MATCH_DECISION_SCHEMA,
    )
    return raw


async def run_phase3(
    vlm_client: VLMClient,
    ads_client: ADSClient,
    image_bytes: bytes,
    food: FoodObject,
    initial_candidates: list[MatchCandidate],
) -> MatchDecision:
    candidates = initial_candidates
    current_food = food
    top3_ever: list[MatchCandidate] = list(initial_candidates[:3])

    for _ in range(MAX_BROADEN_ITERATIONS + 1):
        decision = await _decide_one(vlm_client, image_bytes, current_food, candidates)
        confidence = float(decision["match_confidence"])
        matched_code = decision.get("recipe_code")
        matched = next(
            (c for c in candidates if c.recipe_code == matched_code), None
        )

        if confidence >= ACCEPT_THRESHOLD and matched is not None:
            return MatchDecision(
                food_id=food.id,
                status="accepted",
                matched=matched,
                match_confidence=confidence,
                reasoning=decision["reasoning"],
                candidates_considered=candidates[:3],
            )
        if confidence >= FLAG_THRESHOLD and matched is not None:
            return MatchDecision(
                food_id=food.id,
                status="accepted_flagged",
                matched=matched,
                match_confidence=confidence,
                reasoning=decision["reasoning"],
                candidates_considered=candidates[:3],
            )

        broadened_terms = decision.get("broadened_search_terms") or []
        if not broadened_terms:
            break
        current_food = current_food.model_copy(update={"search_terms": broadened_terms})
        pools = await search_candidates(ads_client, [current_food])
        candidates = [_to_candidate(r) for r in pools[food.id]]
        top3_ever = candidates[:3] or top3_ever

    return MatchDecision(
        food_id=food.id,
        status="unidentified" if top3_ever else "not_found",
        matched=None,
        match_confidence=0.0,
        reasoning="No candidate cleared the match-confidence threshold.",
        candidates_considered=top3_ever,
    )
