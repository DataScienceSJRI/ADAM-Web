import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

import httpx

logger = logging.getLogger("backend.services.whatsapp_gateway")

_SKIP_SUFFIXES = ("@g.us", "@broadcast", "@newsletter")
_PHONE_SUFFIXES = ("@c.us", "@s.whatsapp.net", "@lid")


@dataclass
class IncomingMessage:
    phone: str
    text: str
    message_id: str | None = None


class WhatsAppGateway(ABC):
    @abstractmethod
    def parse_incoming(self, payload: dict) -> IncomingMessage | None:
        ...

    @abstractmethod
    def send_text(self, phone: str, text: str) -> None:
        ...


class WAHAGateway(WhatsAppGateway):
    def __init__(self) -> None:
        self._base_url = os.getenv("WAHA_BASE_URL", "").rstrip("/")
        self._api_key = os.getenv("WAHA_API_KEY", "")
        self._session = os.getenv("WAHA_SESSION", "default")

    def parse_incoming(self, payload: dict) -> IncomingMessage | None:
        if payload.get("event") != "message":
            return None

        data = payload.get("payload") or {}
        if data.get("fromMe"):
            return None

        raw_from = data.get("from") or ""
        if not raw_from or raw_from.endswith(_SKIP_SUFFIXES):
            return None

        phone = raw_from
        for suffix in _PHONE_SUFFIXES:
            if phone.endswith(suffix):
                phone = phone[: -len(suffix)]
                break

        if not phone:
            return None

        return IncomingMessage(
            phone=phone,
            text=(data.get("body") or "").strip(),
            message_id=data.get("id"),
        )

    def send_text(self, phone: str, text: str) -> None:
        if not self._base_url:
            logger.warning("WAHA_BASE_URL not configured — skipping WhatsApp send to %s", phone)
            return
        resp = httpx.post(
            f"{self._base_url}/api/sendText",
            json={"session": self._session, "chatId": f"{phone}@c.us", "text": text},
            headers={"X-Api-Key": self._api_key, "Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()


@lru_cache(maxsize=1)
def get_gateway() -> WhatsAppGateway:
    backend = os.getenv("WHATSAPP_GATEWAY", "waha")
    if backend == "waha":
        return WAHAGateway()
    raise ValueError(f"Unsupported WHATSAPP_GATEWAY: {backend}")
