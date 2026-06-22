import asyncio

from food_id_agent.ads_client import ADSClient, RecipeSearchResult
from food_id_agent.schemas import FoodObject

SEARCH_CONCURRENCY = 8
SEARCH_PAGE_SIZE = 12


async def search_candidates(
    ads_client: ADSClient, foods: list[FoodObject]
) -> dict[str, list[RecipeSearchResult]]:
    """Fire every (food, search_term) pair concurrently, dedup by recipeCode
    per food, preserving ADS's own relevance ranking (first occurrence wins).
    """
    semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def _search_one(food_id: str, term: str) -> tuple[str, list[RecipeSearchResult]]:
        async with semaphore:
            response = await ads_client.search_recipes(
                search_term=term, page_size=SEARCH_PAGE_SIZE
            )
            return food_id, response.recipes

    tasks = [
        _search_one(food.id, term) for food in foods for term in food.search_terms
    ]
    results = await asyncio.gather(*tasks)

    pools: dict[str, dict[str, RecipeSearchResult]] = {food.id: {} for food in foods}
    for food_id, recipes in results:
        for recipe in recipes:
            pools[food_id].setdefault(recipe.recipeCode, recipe)
    return {food_id: list(seen.values()) for food_id, seen in pools.items()}
