"""N3: strong evidence of non-blocking with a real uvicorn server (design D11-N3).

Covers ORB-NFR-017 (the user does not wait for background work). The fake
pipeline stays blocked on a threading event, so the POST must return while the
work is still blocked (causal check — no brittle timing threshold), and after
releasing the event the onboarding state transitions to ingestion_started.
"""

from __future__ import annotations

import socket
import threading
import time

import anyio
import httpx
import uvicorn

from app.main import create_app
from app.core.settings import Settings
from app.modules.ingestion.infrastructure.store import InMemoryOnboardingStateStore
from tests.doubles import FakeHostResolver

PUBLIC_IP = "93.184.216.34"


class EventBlockedPipeline:
    """Pipeline double: waits for an external event, then marks the state started."""

    def __init__(self, store: InMemoryOnboardingStateStore, event: threading.Event) -> None:
        self._store = store
        self._event = event

    async def run(self, onboarding_id) -> None:
        await anyio.to_thread.run_sync(lambda: self._event.wait(10))
        state = self._store.get(onboarding_id)
        state.mark_started()
        self._store.save(state)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_post_returns_while_background_work_is_still_blocked():
    store = InMemoryOnboardingStateStore()
    event = threading.Event()
    app = create_app(
        settings=Settings(app_env="test", log_level="WARNING"),
        resolver=FakeHostResolver([PUBLIC_IP]),
        store=store,
        pipeline=EventBlockedPipeline(store, event),
    )

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn did not start in time"

        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=10
        ) as client:
            started = time.perf_counter()
            response = client.post(
                "/api/v1/onboardings", json={"url": "https://example.com"}
            )
            latency = time.perf_counter() - started

            assert response.status_code == 202
            assert not event.is_set(), (
                "the response arrived after the background work finished; "
                "non-blocking behavior is broken"
            )
            body = response.json()
            current = client.get(f"/api/v1/onboardings/{body['onboarding_id']}")
            assert current.json()["status"] == "received"
            print(f"[N3] POST latency while pipeline blocked: {latency * 1000:.1f} ms")

            event.set()
            final_status = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                final_status = client.get(
                    f"/api/v1/onboardings/{body['onboarding_id']}"
                ).json()["status"]
                if final_status == "ingestion_started":
                    break
                time.sleep(0.05)
            assert final_status == "ingestion_started", (
                "state did not transition after releasing the blocked pipeline"
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()
