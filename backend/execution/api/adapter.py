"""
API Execution Adapter — executes HTTP/REST scenarios via httpx.

Scenario.inputs must contain:
  method  : str  — GET | POST | PUT | PATCH | DELETE
  path    : str  — e.g. "/api/users/123"
  body    : dict — request JSON body (optional)
  params  : dict — query parameters (optional)
  headers : dict — per-request header overrides (optional)

Evidence collected: full request, full response, timing, headers.
Never follows open redirects to external hosts.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import structlog

from backend.adapters.base import ExecutionAdapter
from backend.core.ontology import EvidenceBundle, Scenario
from backend.execution.models import AuthType, ExecutionConfig

log = structlog.get_logger(__name__)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class APIAdapter(ExecutionAdapter):
    """
    HTTP/REST execution adapter backed by httpx.

    One adapter instance per target config; share across scenarios that
    hit the same system (connection pooling).
    """

    def __init__(self, config: ExecutionConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "api"

    @property
    def capabilities(self) -> list[str]:
        return ["discover", "execute", "observe"]

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {**self._config.default_headers}
        cfg = self._config
        if cfg.auth_type == AuthType.BEARER and cfg.auth_value:
            headers[cfg.auth_header] = f"Bearer {cfg.auth_value}"
        elif cfg.auth_type == AuthType.API_KEY and cfg.auth_value:
            headers[cfg.auth_header] = cfg.auth_value
        elif cfg.auth_type == AuthType.BASIC and cfg.auth_value:
            import base64
            encoded = base64.b64encode(cfg.auth_value.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        if extra:
            headers.update(extra)
        return headers

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(self._config.timeout_seconds),
            verify=self._config.verify_tls,
            follow_redirects=False,
        )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "APIAdapter":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    async def execute(self, scenario: Scenario) -> EvidenceBundle:
        if not self._client:
            await self.connect()

        inputs = scenario.inputs
        method = str(inputs.get("method", "GET")).upper()
        path = str(inputs.get("path", "/"))
        body: dict | None = inputs.get("body")
        params: dict | None = inputs.get("params")
        extra_headers: dict | None = inputs.get("headers")

        if method not in _ALLOWED_METHODS:
            raise ValueError(f"Unsupported HTTP method: {method}")

        headers = self._build_headers(extra_headers)

        # Apply actor identity to headers (e.g. override auth for boundary tests)
        actor = scenario.actor_identity
        if actor.get("token_expired"):
            headers["Authorization"] = "Bearer expired.token.value"
        elif actor.get("authenticated") is False or not actor:
            headers.pop("Authorization", None)

        request_record: dict[str, Any] = {
            "method": method,
            "path": path,
            "params": params,
            "body": body,
            "headers": {k: v for k, v in headers.items() if k.lower() != "authorization"},
        }

        t0 = time.monotonic()
        try:
            response = await self._client.request(
                method,
                path,
                json=body,
                params=params,
                headers=headers,
            )
            duration_ms = (time.monotonic() - t0) * 1000

            response_body: Any = None
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    response_body = response.json()
                except Exception:
                    response_body = response.text
            else:
                response_body = response.text[:4096]  # cap non-JSON

            response_record: dict[str, Any] = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response_body,
                "duration_ms": round(duration_ms, 2),
                "url": str(response.url),
            }

            log.debug(
                "api_executed",
                method=method,
                path=path,
                status=response.status_code,
                duration_ms=round(duration_ms),
            )

        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Request timed out: {method} {path}") from exc
        except httpx.RequestError as exc:
            raise ConnectionError(f"Request failed: {exc}") from exc

        return EvidenceBundle(
            id=uuid4(),
            execution_id=uuid4(),
            scenario_id=scenario.id,
            captured_at=datetime.now(timezone.utc),
            request=request_record,
            response=response_record,
            environment_snapshot={"base_url": self._config.base_url},
        )

    async def discover(self) -> dict[str, Any]:
        """
        Attempt to discover API structure via OpenAPI spec endpoints.
        Returns whatever is found; callers handle missing spec gracefully.
        """
        if not self._client:
            await self.connect()

        for path in ("/openapi.json", "/api/openapi.json", "/swagger.json", "/docs/openapi.json"):
            try:
                resp = await self._client.get(path)
                if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                    spec = resp.json()
                    return {"found": True, "path": path, "spec": spec}
            except Exception:
                continue

        return {"found": False}
