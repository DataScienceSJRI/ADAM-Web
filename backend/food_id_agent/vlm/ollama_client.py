import base64
import json
import time

import ollama

from food_id_agent.logging_utils import logger


class OllamaVLMClient:
    def __init__(self, host: str, model: str) -> None:
        self._client = ollama.AsyncClient(host=host)
        self._model = model
        self._host = host

    async def complete_structured(
        self,
        *,
        image_bytes: bytes,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
    ) -> dict:
        image_b64 = base64.b64encode(image_bytes).decode()
        logger.debug(
            "Ollama request: host=%s model=%s image_kb=%d\n  system=%r\n  user=%r",
            self._host,
            self._model,
            len(image_bytes) // 1024,
            system_prompt,
            user_prompt,
        )
        t0 = time.monotonic()
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt, "images": [image_b64]},
                ],
                format=json_schema,
            )
        except Exception:
            logger.exception(
                "Ollama request failed after %.2fs", time.monotonic() - t0
            )
            raise
        elapsed = time.monotonic() - t0
        content = response["message"]["content"]
        logger.debug("Ollama response in %.2fs: %s", elapsed, content)
        return json.loads(content)
