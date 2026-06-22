import base64
import json
import time

from openai import AsyncOpenAI

from food_id_agent.logging_utils import logger


class OpenAIVLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete_structured(
        self,
        *,
        image_bytes: bytes,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
    ) -> dict:
        data_url = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"
        logger.debug(
            "OpenAI request: model=%s image_kb=%d\n  system=%r\n  user=%r",
            self._model,
            len(image_bytes) // 1024,
            system_prompt,
            user_prompt,
        )
        t0 = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "schema": json_schema,
                        "strict": True,
                    },
                },
            )
        except Exception:
            logger.exception(
                "OpenAI request failed after %.2fs", time.monotonic() - t0
            )
            raise
        elapsed = time.monotonic() - t0
        content = response.choices[0].message.content
        logger.debug("OpenAI response in %.2fs: %s", elapsed, content)
        return json.loads(content)
