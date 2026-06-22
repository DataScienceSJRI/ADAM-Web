from food_id_agent.schemas import FoodObject, SceneAnalysis
from food_id_agent.vlm.base import VLMClient

MAX_FOOD_ITEMS = 12

SCENE_ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "foods": {
            "type": "array",
            "maxItems": MAX_FOOD_ITEMS,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "visual_context": {"type": "string"},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "description", "visual_context", "search_terms"],
                "additionalProperties": False,
            },
        },
        "plate_context": {
            "type": "object",
            "properties": {
                "container_type": {"type": ["string", "null"]},
                "estimated_diameter_cm": {"type": ["number", "null"]},
                "reference_objects": {"type": "array", "items": {"type": "string"}},
                "fill_level_pct": {"type": ["number", "null"]},
            },
            "required": [
                "container_type",
                "estimated_diameter_cm",
                "reference_objects",
                "fill_level_pct",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["foods", "plate_context"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a food scene analysis assistant. Your only job is to identify "
    "edible food and drink items visible in the image, and to describe the "
    "plate/container context. You must ignore everything that is not "
    "edible — plates, cutlery, trays, fingers, table surface, background, "
    "shadows, lighting, reflections, packaging, and any other non-food "
    "object. Never invent or repeat items: each real dish or drink appears "
    "in your output exactly once, even if it is visible in multiple spots "
    "on the plate."
)

USER_PROMPT = (
    f"Identify each distinct edible food or drink item visible, up to a "
    f"maximum of {MAX_FOOD_ITEMS} items. Do not list non-food objects "
    "(plate, tray, spoon, fingers, background, shadows, etc.) and do not "
    "list the same dish more than once. For each food, give a short id, a "
    "description, visual context (placement, garnish, etc.), and 3-5 "
    "search terms on a specificity gradient (exact local name, "
    "common/short name, preparation variant, regional alias). "
    "Include at least one single- or two-word term per food."
)


def _dedupe_foods(foods: list[FoodObject]) -> list[FoodObject]:
    seen: set[str] = set()
    deduped: list[FoodObject] = []
    for food in foods:
        key = food.description.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(food)
        if len(deduped) >= MAX_FOOD_ITEMS:
            break
    return deduped


async def run_phase1(vlm_client: VLMClient, image_bytes: bytes) -> SceneAnalysis:
    raw = await vlm_client.complete_structured(
        image_bytes=image_bytes,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT,
        json_schema=SCENE_ANALYSIS_SCHEMA,
    )
    scene = SceneAnalysis.model_validate(raw)
    scene.foods = _dedupe_foods(scene.foods)
    return scene
