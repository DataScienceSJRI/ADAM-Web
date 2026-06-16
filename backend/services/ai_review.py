import logging
import os
from typing import Optional

logger = logging.getLogger("backend.services.ai_review")

_PROMPT = (
    "You are a clinical nutrition analyst reviewing meal compliance images for a diabetes research study. "
    "Analyse the provided pre-meal and/or post-meal images and give a structured assessment:\n"
    "1. Pre-meal: What food/drink is visible? Estimate portion size.\n"
    "2. Post-meal: How much was consumed? Any food remaining?\n"
    "3. Compliance: Does the post-meal image suggest the participant ate as intended?\n"
    "4. Notes: Any concerns (e.g. unapproved foods, large portion mismatch).\n"
    "Be concise and clinical. Do not make medical diagnoses."
)


def analyse_meal_images(pre_url: Optional[str], post_url: Optional[str]) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return "OpenAI package not installed. Run: pip install openai"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY not configured."

    if not pre_url and not post_url:
        return "No images provided for analysis."

    content: list = [{"type": "text", "text": _PROMPT}]
    if pre_url:
        content += [
            {"type": "text", "text": "Pre-meal image:"},
            {"type": "image_url", "image_url": {"url": pre_url, "detail": "low"}},
        ]
    if post_url:
        content += [
            {"type": "text", "text": "Post-meal image:"},
            {"type": "image_url", "image_url": {"url": post_url, "detail": "low"}},
        ]

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=600,
        )
        return resp.choices[0].message.content or "No analysis returned."
    
    except Exception as exc:
        logger.exception("OpenAI analysis failed")
        return f"AI analysis failed: {exc}"