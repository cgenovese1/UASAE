"""
Browser Execution Adapter — drives a real browser via Playwright.

Scenario.inputs must contain:
  url      : str         — starting URL
  actions  : list[dict]  — sequence of browser actions (click, type, navigate, ...)
  viewport : dict        — {"width": 1280, "height": 720} (optional)

Action format:
  {"type": "navigate",  "url": "..."}
  {"type": "click",     "selector": "..."}
  {"type": "type",      "selector": "...", "text": "..."}
  {"type": "wait",      "selector": "..."}
  {"type": "assert",    "selector": "...", "text": "..."}
  {"type": "screenshot"}

Evidence collected: screenshots, DOM snapshot, console errors, network requests.

If Playwright is not installed, scenarios fall back to UNOBSERVABLE
rather than crashing — install with: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from backend.adapters.base import ExecutionAdapter
from backend.core.ontology import EvidenceBundle, Scenario
from backend.execution.models import ExecutionConfig

log = structlog.get_logger(__name__)

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


class BrowserNotAvailable(RuntimeError):
    """Raised when Playwright is not installed."""


class BrowserAdapter(ExecutionAdapter):
    """
    Playwright-backed browser execution adapter.
    Headless Chromium by default; configurable to Firefox or WebKit.
    """

    def __init__(self, config: ExecutionConfig, browser_type: str = "chromium") -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise BrowserNotAvailable(
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        self._config = config
        self._browser_type = browser_type
        self._pw: Any = None
        self._browser: Any = None

    @property
    def name(self) -> str:
        return "browser"

    @property
    def capabilities(self) -> list[str]:
        return ["execute", "observe", "snapshot"]

    @classmethod
    def is_available(cls) -> bool:
        return _PLAYWRIGHT_AVAILABLE

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        self._pw = await async_playwright().start()
        launcher = getattr(self._pw, self._browser_type)
        self._browser = await launcher.launch(headless=True)

    async def disconnect(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def __aenter__(self) -> "BrowserAdapter":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    async def execute(self, scenario: Scenario) -> EvidenceBundle:
        inputs = scenario.inputs
        start_url = inputs.get("url", self._config.base_url)
        actions: list[dict] = inputs.get("actions", [{"type": "navigate", "url": start_url}])
        viewport = inputs.get("viewport", {"width": 1280, "height": 720})

        context: Any = await self._browser.new_context(
            viewport=viewport,
            ignore_https_errors=not self._config.verify_tls,
        )

        # Apply auth cookie / storage state if provided
        actor = scenario.actor_identity
        if actor.get("cookie"):
            await context.add_cookies([actor["cookie"]])

        page: Any = await context.new_page()

        console_errors: list[str] = []
        network_requests: list[dict] = []

        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
        page.on("request", lambda req: network_requests.append({"url": req.url, "method": req.method}))

        screenshots: list[str] = []
        ui_states: list[dict] = []
        action_log: list[dict] = []

        for action in actions:
            act_type = action.get("type", "")
            try:
                if act_type == "navigate":
                    url = action.get("url", start_url)
                    await page.goto(url, wait_until="networkidle", timeout=15_000)
                    action_log.append({"type": "navigate", "url": url, "status": "ok"})

                elif act_type == "click":
                    sel = action["selector"]
                    await page.click(sel, timeout=10_000)
                    action_log.append({"type": "click", "selector": sel, "status": "ok"})

                elif act_type == "type":
                    sel = action["selector"]
                    text = action.get("text", "")
                    await page.fill(sel, text)
                    action_log.append({"type": "type", "selector": sel, "status": "ok"})

                elif act_type == "wait":
                    sel = action.get("selector")
                    ms = action.get("ms", 500)
                    if sel:
                        await page.wait_for_selector(sel, timeout=10_000)
                    else:
                        await page.wait_for_timeout(ms)
                    action_log.append({"type": "wait", "status": "ok"})

                elif act_type == "screenshot":
                    png = await page.screenshot(full_page=action.get("full_page", False))
                    b64 = base64.b64encode(png).decode()
                    screenshots.append(b64)
                    action_log.append({"type": "screenshot", "status": "ok"})

                elif act_type == "assert":
                    sel = action.get("selector")
                    expected = action.get("text", "")
                    if sel:
                        el = await page.query_selector(sel)
                        actual = await el.inner_text() if el else None
                        passed = actual is not None and expected.lower() in (actual or "").lower()
                    else:
                        content = await page.content()
                        passed = expected.lower() in content.lower()
                    action_log.append({
                        "type": "assert",
                        "selector": sel,
                        "expected": expected,
                        "passed": passed,
                    })

            except Exception as exc:
                action_log.append({"type": act_type, "status": "error", "error": str(exc)})
                log.warning("browser_action_failed", action_type=act_type, error=str(exc))

        # Final DOM snapshot
        try:
            dom = await page.content()
            ui_state: dict = {
                "url": page.url,
                "title": await page.title(),
                "dom_length": len(dom),
                "action_log": action_log,
                "console_errors": console_errors[:20],
            }
        except Exception:
            ui_state = {"error": "failed to capture DOM state"}

        await context.close()

        return EvidenceBundle(
            id=uuid4(),
            execution_id=uuid4(),
            scenario_id=scenario.id,
            captured_at=datetime.now(timezone.utc),
            ui_state=ui_state,
            screenshot_ref=screenshots[-1] if screenshots else None,
            logs=console_errors,
            network_ref=str(network_requests[:50]) if network_requests else None,
            environment_snapshot={"base_url": self._config.base_url, "browser": self._browser_type},
        )
