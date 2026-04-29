from __future__ import annotations

from typing import Any

import httpx
from code_analyst_contracts import (
    SandboxDisposeRequest,
    SandboxDisposeResponse,
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxSessionCreateRequest,
    SandboxSessionRef,
)


class SandboxSupervisorClientError(RuntimeError):
    pass


class SandboxSupervisorClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 280.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def create_session(
        self,
        request: SandboxSessionCreateRequest,
    ) -> SandboxSessionRef:
        response = await self._request(
            "POST",
            "/v1/sandboxes/sessions",
            json=request.model_dump(mode="json"),
        )
        return SandboxSessionRef.model_validate(response.json())

    async def execute_session(
        self,
        sandbox_id: str,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResponse:
        response = await self._request(
            "POST",
            f"/v1/sandboxes/{sandbox_id}/execute",
            json=request.model_dump(mode="json"),
        )
        return SandboxExecutionResponse.model_validate(response.json())

    async def dispose_session(
        self,
        sandbox_id: str,
        request: SandboxDisposeRequest | None = None,
    ) -> SandboxDisposeResponse:
        payload = (
            request.model_dump(mode="json")
            if request is not None
            else SandboxDisposeRequest().model_dump(mode="json")
        )
        response = await self._request(
            "DELETE",
            f"/v1/sandboxes/{sandbox_id}",
            json=payload,
        )
        return SandboxDisposeResponse.model_validate(response.json())

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=self._timeout_seconds,
        ) as client:
            response = await client.request(method, path, **kwargs)
        if response.is_error:
            detail = response.text.strip() or response.reason_phrase
            raise SandboxSupervisorClientError(
                f"Sandbox supervisor request failed ({response.status_code}): {detail}"
            )
        return response
