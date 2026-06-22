from typing import Protocol


class VLMClient(Protocol):
    async def complete_structured(
        self,
        *,
        image_bytes: bytes,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
    ) -> dict:
        """Send one multimodal request and return a dict conforming to json_schema.

        Callers must still validate the returned dict against the matching
        Pydantic model — schema-constrained generation reduces malformed JSON
        but doesn't guarantee semantically sane values.
        """
        ...
