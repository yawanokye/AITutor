from __future__ import annotations

from typing import Any
import httpx

from app.config import Settings


class TavusError(RuntimeError):
    pass


class TavusService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def headers(self) -> dict[str, str]:
        return {"x-api-key": self.settings.tavus_api_key, "Content-Type": "application/json"}

    async def create_video(
        self,
        *,
        title: str,
        script: str,
        background_url: str = "",
    ) -> dict[str, Any]:
        if not self.settings.tavus_video_ready:
            raise TavusError("Tavus lesson-video generation is not configured.")
        payload: dict[str, Any] = {
            "replica_id": self.settings.tavus_video_replica_id,
            "script": script[: self.settings.max_video_script_chars],
            "video_name": title[:180],
            "fast": self.settings.tavus_video_fast,
        }
        if background_url:
            payload["background_url"] = background_url
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.settings.tavus_base_url}/v2/videos",
                headers=self.headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise TavusError(self._error_message(response))
        return response.json()

    async def get_video(self, video_id: str) -> dict[str, Any]:
        if not self.settings.tavus_api_key:
            raise TavusError("Tavus is not configured.")
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(
                f"{self.settings.tavus_base_url}/v2/videos/{video_id}",
                headers={"x-api-key": self.settings.tavus_api_key},
                params={"verbose": "true"},
            )
        if response.status_code >= 400:
            raise TavusError(self._error_message(response))
        return response.json()

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("message") or data.get("error") or data.get("detail")
            if message:
                return f"Tavus error: {message}"
        except ValueError:
            pass
        return f"Tavus request failed with status {response.status_code}."
