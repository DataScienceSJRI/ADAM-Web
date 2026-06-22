import asyncio
import base64
import json
import time

import httpx
from pydantic import BaseModel

from food_id_agent.logging_utils import logger


class Token(BaseModel):
    access_token: str
    refresh_token: str | None
    token_type: str


class RecipeSearchResult(BaseModel):
    recipeCode: str
    recipeName: str | None = None
    recipeCategory: str | None = None
    cookingTime: str | None = None
    Code_cooccurence: str | None = None
    Custom_recipe: int | None = None
    F: str | None = None
    Energy_Kcal: float | None = None
    Portion: float | None = None
    Recipe_Description: str | None = None
    recipeWeightG: float | None = None


class RecipeSearchResponse(BaseModel):
    recipes: list[RecipeSearchResult]
    total_count: int
    page: int
    page_size: int
    search_term: str | None = None
    recipe_category: str | None = None
    subcategories: str | None = None
    max_cooking_time: int | None = None
    preference: str | None = None
    custom: bool | None = None


def _decode_jwt_exp(access_token: str) -> float | None:
    try:
        payload_segment = access_token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
        return payload.get("exp")
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


class ADSClient:
    """Owns the ADS token lifecycle and the only HTTP calls this project makes:
    login, refresh, and recipe search. No other ADS endpoint is in scope.
    """

    REFRESH_MARGIN_SECONDS = 5 * 60

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)
        self._token: Token | None = None
        self._token_exp: float | None = None
        self._refresh_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def login(self) -> None:
        logger.info("ADS login: POST /api/v1/auth/login (user=%s)", self._username)
        response = await self._http.post(
            "/api/v1/auth/login",
            data={
                "username": self._username,
                "password": self._password,
                "grant_type": "password",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        self._set_token(Token.model_validate(response.json()))
        logger.info("ADS login OK")

    def _set_token(self, token: Token) -> None:
        self._token = token
        self._token_exp = _decode_jwt_exp(token.access_token)

    async def _refresh(self, stale_token: str | None) -> None:
        """Refresh the token, guarded by a lock so concurrent 401s collapse
        into a single network refresh. `stale_token` is the access token the
        caller observed as invalid; if another caller already replaced it by
        the time this one acquires the lock, skip the redundant network call.
        """
        async with self._refresh_lock:
            if (
                stale_token is not None
                and self._token is not None
                and self._token.access_token != stale_token
            ):
                return
            if self._token is None or self._token.refresh_token is None:
                await self.login()
                return
            logger.info("ADS refresh: POST /api/v1/auth/refresh")
            try:
                response = await self._http.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": self._token.refresh_token},
                )
                response.raise_for_status()
                self._set_token(Token.model_validate(response.json()))
                logger.info("ADS refresh OK")
            except httpx.HTTPStatusError as exc:
                logger.warning("ADS refresh failed (%s), falling back to login", exc)
                await self.login()

    def _token_fresh(self) -> bool:
        if self._token is None or self._token_exp is None:
            return False
        return time.time() < self._token_exp - self.REFRESH_MARGIN_SECONDS

    async def _ensure_token(self) -> str:
        if self._token is None:
            await self.login()
        elif not self._token_fresh():
            await self._refresh(self._token.access_token)
        return self._token.access_token

    async def _authed_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        response = await self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401:
            await self._refresh(token)
            headers["Authorization"] = f"Bearer {self._token.access_token}"
            response = await self._http.request(method, path, headers=headers, **kwargs)
            if response.status_code == 401:
                await self.login()
                headers["Authorization"] = f"Bearer {self._token.access_token}"
                response = await self._http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    async def search_recipes(
        self,
        *,
        search_term: str | None = None,
        recipe_category: str | None = None,
        subcategories: str | None = None,
        max_cooking_time: int | None = None,
        custom: bool = False,
        sort_on: str | None = None,
        sort_type: bool = True,
        page: int = 1,
        page_size: int = 10,
    ) -> RecipeSearchResponse:
        params = {
            "search_term": search_term,
            "recipe_category": recipe_category,
            "subcategories": subcategories,
            "max_cooking_time": max_cooking_time,
            "custom": custom,
            "sort_on": sort_on,
            "sort_type": sort_type,
            "page": page,
            "page_size": page_size,
        }
        params = {k: v for k, v in params.items() if v is not None}
        logger.debug("ADS search: GET /api/v1/recipes/search params=%s", params)
        t0 = time.monotonic()
        response = await self._authed_request(
            "GET", "/api/v1/recipes/search", params=params
        )
        result = RecipeSearchResponse.model_validate(response.json())
        logger.debug(
            "ADS search done in %.2fs: term=%r -> %d recipe(s) (total_count=%d)",
            time.monotonic() - t0,
            search_term,
            len(result.recipes),
            result.total_count,
        )
        return result
