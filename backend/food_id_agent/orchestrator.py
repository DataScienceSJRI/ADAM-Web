import asyncio
import time
from typing import Callable

from food_id_agent.ads_client import ADSClient
from food_id_agent.config import Settings, get_settings
from food_id_agent.logging_utils import logger, new_run_id, run_log_file
from food_id_agent.pipeline.phase1_scene import run_phase1
from food_id_agent.pipeline.phase2_search import search_candidates
from food_id_agent.pipeline.phase3_match import _to_candidate, run_phase3
from food_id_agent.pipeline.phase4_quantity import run_phase4
from food_id_agent.schemas import FoodResult, PipelineOutput
from food_id_agent.vlm.base import VLMClient
from food_id_agent.vlm.ollama_client import OllamaVLMClient
from food_id_agent.vlm.openai_client import OpenAIVLMClient

# (phase_label, message, elapsed_seconds_for_this_step_or_None)
ProgressCallback = Callable[[str, str, float | None], None]


def _build_vlm_client(settings: Settings) -> VLMClient:
    if settings.vlm_backend == "openai":
        return OpenAIVLMClient(api_key=settings.openai_api_key, model=settings.openai_model)
    return OllamaVLMClient(host=settings.ollama_host, model=settings.ollama_model)


async def run_pipeline(
    image_bytes: bytes,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> PipelineOutput:
    settings = settings or get_settings()
    run_id = new_run_id()

    def emit(phase: str, message: str, elapsed: float | None = None) -> None:
        logger.info("[%s] %s%s", phase, message, f" ({elapsed:.2f}s)" if elapsed is not None else "")
        if on_progress is not None:
            on_progress(phase, message, elapsed)

    with run_log_file(run_id) as log_path:
        logger.info(
            "Run %s starting: backend=%s model=%s image_kb=%d",
            run_id,
            settings.vlm_backend,
            settings.openai_model if settings.vlm_backend == "openai" else settings.ollama_model,
            len(image_bytes) // 1024,
        )
        emit("Setup", f"Log file: {log_path}")
        try:
            output = await _run_pipeline_phases(image_bytes, settings, run_id, emit)
            logger.info("Run %s finished OK", run_id)
            return output
        except Exception:
            logger.exception("Run %s failed", run_id)
            raise


async def _run_pipeline_phases(
    image_bytes: bytes, settings: Settings, run_id: str, emit: Callable[..., None]
) -> PipelineOutput:
    vlm_client = _build_vlm_client(settings)
    ads_client = ADSClient(
        base_url=settings.ads_base_url,
        username=settings.ads_username,
        password=settings.ads_password,
    )

    try:
        emit(
            "Phase 1",
            f"Analyzing scene with {settings.vlm_backend} "
            f"({settings.openai_model if settings.vlm_backend == 'openai' else settings.ollama_model})...",
        )
        t0 = time.monotonic()
        scene = await run_phase1(vlm_client, image_bytes)
        emit(
            "Phase 1",
            f"Found {len(scene.foods)} food item(s): "
            + ", ".join(f.description for f in scene.foods),
            time.monotonic() - t0,
        )

        emit(
            "Phase 2",
            f"Searching ADS recipes for {sum(len(f.search_terms) for f in scene.foods)} "
            f"(food x search_term) pairs across {len(scene.foods)} food(s)...",
        )
        t0 = time.monotonic()
        candidate_pools = await search_candidates(ads_client, scene.foods)
        emit(
            "Phase 2",
            "Candidate pool sizes: "
            + ", ".join(f"{fid}={len(pool)}" for fid, pool in candidate_pools.items()),
            time.monotonic() - t0,
        )

        flags: list[str] = []
        results: list[FoodResult] = []
        for food in scene.foods:
            candidates = [_to_candidate(r) for r in candidate_pools[food.id]]

            emit("Phase 3", f"Matching '{food.description}' against {len(candidates)} candidate(s)...")
            t0 = time.monotonic()
            match = await run_phase3(vlm_client, ads_client, image_bytes, food, candidates)
            match_summary = (
                f"-> {match.status} (confidence {match.match_confidence:.2f})"
                + (f": {match.matched.recipe_name}" if match.matched else "")
            )
            emit("Phase 3", f"'{food.description}' {match_summary}", time.monotonic() - t0)

            emit("Phase 4", f"Estimating quantity for '{food.description}'...")
            t0 = time.monotonic()
            quantity = await run_phase4(vlm_client, image_bytes, match)
            if quantity is not None:
                emit(
                    "Phase 4",
                    f"'{food.description}' -> {quantity.quantity_g:.0f}g "
                    f"({quantity.quantity_g_min:.0f}-{quantity.quantity_g_max:.0f}g, "
                    f"{quantity.quantity_confidence} confidence, {quantity.quantity_method})",
                    time.monotonic() - t0,
                )
            else:
                emit("Phase 4", f"'{food.description}' skipped (no accepted match)", time.monotonic() - t0)

            if match.status == "unidentified":
                flags.append(f"{food.id}: unidentified, needs human review")
            if quantity is not None and quantity.quantity_method == "category_prior_fallback":
                flags.append(f"{food.id}: no recipe_weight_g, used category prior fallback")

            results.append(FoodResult(food_id=food.id, match=match, quantity=quantity))

        emit("Done", f"Pipeline complete: {len(results)} food(s), {len(flags)} flag(s).")

        return PipelineOutput(
            analysis_id=run_id,
            foods=results,
            plate_context=scene.plate_context,
            flags=flags,
        )
    finally:
        await ads_client.aclose()


def run_pipeline_sync(
    image_bytes: bytes,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> PipelineOutput:
    return asyncio.run(run_pipeline(image_bytes, settings, on_progress))
