"""WhatsApp Cloud API (Graph) client for messaging.

Calls are handled by the telephony provider; this module covers messages:
send text, mark read with a typing indicator, fetch voice notes.
"""

from __future__ import annotations

from typing import Any

import httpx

GRAPH_URL = "https://graph.facebook.com/v23.0"
TIMEOUT = httpx.Timeout(20.0)
MAX_TEXT = 4096  # WhatsApp text message limit
MAX_MEDIA_BYTES = 16 * 1024 * 1024


class WhatsAppSendError(RuntimeError):
    pass


class WhatsAppMessenger:
    def __init__(self, phone_number_id: str, access_token: str, transport=None):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=TIMEOUT,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    async def send_text(
        self, to: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        """Send one text; long answers are split on paragraph boundaries."""
        last_id = None
        for chunk in split_text(body):
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": chunk, "preview_url": True},
            }
            if reply_to and last_id is None:
                payload["context"] = {"message_id": reply_to}
            async with self._client() as client:
                response = await client.post(
                    f"{GRAPH_URL}/{self.phone_number_id}/messages", json=payload
                )
            if response.status_code >= 300:
                detail = ""
                try:
                    detail = response.json().get("error", {}).get("message", "")
                except ValueError:
                    pass
                raise WhatsAppSendError(
                    f"WhatsApp refused the message ({response.status_code}) {detail}".strip()
                )
            messages = response.json().get("messages") or [{}]
            last_id = messages[0].get("id")
        return last_id

    async def mark_read(self, message_id: str, *, typing: bool = True) -> None:
        """Blue ticks, plus "typing…" while the agent prepares its answer."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        try:
            async with self._client() as client:
                await client.post(
                    f"{GRAPH_URL}/{self.phone_number_id}/messages", json=payload
                )
        except httpx.HTTPError:
            pass  # cosmetic

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        async with self._client() as client:
            meta = await client.get(f"{GRAPH_URL}/{media_id}")
            if meta.status_code >= 300:
                raise WhatsAppSendError(f"Media lookup failed ({meta.status_code})")
            info = meta.json()
            if int(info.get("file_size") or 0) > MAX_MEDIA_BYTES:
                raise WhatsAppSendError("Media too large")
            media = await client.get(info["url"])
            if media.status_code >= 300:
                raise WhatsAppSendError(f"Media download failed ({media.status_code})")
            return media.content, info.get("mime_type") or "audio/ogg"


def split_text(body: str, limit: int = MAX_TEXT) -> list[str]:
    text = (body or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        candidate = f"{current}\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def message_text(message: dict[str, Any]) -> tuple[str | None, str | None]:
    """(text, media_id_of_voice_note) for one inbound webhook message."""
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body"), None
    if kind == "audio":
        return None, (message.get("audio") or {}).get("id")
    if kind == "button":
        return (message.get("button") or {}).get("text"), None
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title"), None
    if kind == "location":
        loc = message.get("location") or {}
        parts = [loc.get("name"), loc.get("address")]
        where = ", ".join(p for p in parts if p)
        coords = f"{loc.get('latitude')}, {loc.get('longitude')}"
        return (
            f"[Localisation partagée : {where + ' — ' if where else ''}{coords}]",
            None,
        )
    if kind in {"image", "document", "video", "sticker"}:
        caption = (message.get(kind) or {}).get("caption")
        label = {
            "image": "photo",
            "document": "document",
            "video": "vidéo",
            "sticker": "sticker",
        }[kind]
        return (
            f"[Le client a envoyé une {label}{' : ' + caption if caption else ''}]",
            None,
        )
    if kind == "contacts":
        contacts = message.get("contacts") or []
        names = [((c.get("name") or {}).get("formatted_name")) for c in contacts]
        phones = [p.get("phone") for c in contacts for p in (c.get("phones") or [])]
        return (
            f"[Contact partagé : {', '.join(n for n in names if n)} {', '.join(p for p in phones if p)}]",
            None,
        )
    return None, None
