from food_id_agent.schemas import MatchDecision, QuantityEstimate
from food_id_agent.vlm.base import VLMClient

SERVING_MULTIPLIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "serving_multiplier_min": {"type": "number"},
        "serving_multiplier_max": {"type": "number"},
        "estimation_reasoning": {"type": "string"},
    },
    "required": [
        "serving_multiplier_min",
        "serving_multiplier_max",
        "estimation_reasoning",
    ],
    "additionalProperties": False,
}

DIRECT_ESTIMATE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "quantity_g_min": {"type": "number"},
        "quantity_g_max": {"type": "number"},
        "estimation_reasoning": {"type": "string"},
    },
    "required": ["quantity_g_min", "quantity_g_max", "estimation_reasoning"],
    "additionalProperties": False,
}

REFERENCE_HIERARCHY = (
    "hand in frame > cutlery > known-size food items > standard steel plate "
    "~26cm > standard bowl ~300-400ml > prior-only"
)


async def run_phase4(
    vlm_client: VLMClient, image_bytes: bytes, match: MatchDecision
) -> QuantityEstimate | None:
    if match.status not in ("accepted", "accepted_flagged") or match.matched is None:
        return None

    recipe = match.matched
    if recipe.recipe_weight_g is not None:
        raw = await vlm_client.complete_structured(
            image_bytes=image_bytes,
            system_prompt=(
                "You are a food portion-size estimation assistant. Estimate "
                "the serving multiplier visible in the photo relative to a "
                "known standard serving weight."
            ),
            user_prompt=(
                f"The matched recipe is {recipe.recipe_name!r} with a standard "
                f"serving weight of {recipe.recipe_weight_g}g. Estimate the "
                "multiplier of that standard serving visible in the photo "
                "(e.g. 1.3x), as a min/max range."
            ),
            json_schema=SERVING_MULTIPLIER_SCHEMA,
        )
        mult_min = float(raw["serving_multiplier_min"])
        mult_max = float(raw["serving_multiplier_max"])
        mult_mid = (mult_min + mult_max) / 2
        return QuantityEstimate(
            food_id=match.food_id,
            quantity_g=mult_mid * recipe.recipe_weight_g,
            quantity_g_min=mult_min * recipe.recipe_weight_g,
            quantity_g_max=mult_max * recipe.recipe_weight_g,
            serving_multiplier=mult_mid,
            quantity_confidence="high" if match.status == "accepted" else "medium",
            quantity_method="serving_multiplier",
            estimation_reasoning=raw["estimation_reasoning"],
        )

    raw = await vlm_client.complete_structured(
        image_bytes=image_bytes,
        system_prompt=(
            "You are a food portion-size estimation assistant. No database "
            "weight anchor is available — estimate grams directly using "
            f"this reference-object priority: {REFERENCE_HIERARCHY}."
        ),
        user_prompt=(
            f"The matched recipe is {recipe.recipe_name!r}, but it has no "
            "standard serving weight on file. Estimate the visible quantity "
            "in grams directly from the image, as a min/max range."
        ),
        json_schema=DIRECT_ESTIMATE_SCHEMA,
    )
    return QuantityEstimate(
        food_id=match.food_id,
        quantity_g=(raw["quantity_g_min"] + raw["quantity_g_max"]) / 2,
        quantity_g_min=raw["quantity_g_min"],
        quantity_g_max=raw["quantity_g_max"],
        serving_multiplier=None,
        quantity_confidence="low",
        quantity_method="category_prior_fallback",
        estimation_reasoning=raw["estimation_reasoning"],
    )
