import logging
import os

import httpx

logger = logging.getLogger("backend.services.food_id")


def _build_settings(vlm_backend: str | None = None):
    try:
        from food_id_agent.config import Settings
    except ImportError as exc:
        raise RuntimeError(
            "food_id_agent is not installed. "
            "Run: pip install git+https://github.com/ictashik/FVA.git"
        ) from exc
    return Settings(
        _env_file=None,  # prevent loading backend's .env — values supplied explicitly
        ads_base_url=os.environ.get("ADS_BASE_URL", "https://datatools.sjri.res.in/ADS"),
        ads_username=os.environ.get("ADS_USERNAME", ""),
        ads_password=os.environ.get("ADS_PASSWORD", ""),
        vlm_backend=vlm_backend or os.environ.get("VLM_BACKEND", "openai"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "gemma4:26b"),
    )


async def identify_image_from_url(image_url: str, vlm_backend: str | None = None) -> dict:
    """Download image bytes from a URL and run the food identification pipeline."""
    try:
        from food_id_agent.orchestrator import run_pipeline
    except ImportError as exc:
        raise RuntimeError(
            "food_id_agent is not installed. "
            "Run: pip install git+https://github.com/ictashik/FVA.git"
        ) from exc

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        image_bytes = resp.content

    import inspect
    settings = _build_settings(vlm_backend)
    sig = inspect.signature(run_pipeline)
    if "settings" in sig.parameters:
        output = await run_pipeline(image_bytes, settings=settings)
    else:
        # orchestrator reads from env vars via pydantic-settings — patch them in
        env_patch = {
            "VLM_BACKEND": settings.vlm_backend,
            "OLLAMA_HOST": settings.ollama_host,
            "OLLAMA_MODEL": settings.ollama_model,
            "OPENAI_MODEL": settings.openai_model,
        }
        import os
        old = {k: os.environ.get(k) for k in env_patch}
        os.environ.update(env_patch)
        try:
            output = await run_pipeline(image_bytes)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return output.model_dump()


def identify_image_from_url_sync(image_url: str, vlm_backend: str | None = None) -> dict:
    """Synchronous wrapper — safe to call from a FastAPI sync route handler."""
    import asyncio
    return asyncio.run(identify_image_from_url(image_url, vlm_backend))