"""Application factory and composition root for the ORBIT backend.

The concrete adapters are wired here and exposed on `app.state`; `create_app()`
accepts overrides so tests can inject doubles without touching the domain
(ORB-CON-015, design D5). The module-level `app` keeps `uvicorn app.main:app`
working.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Request, Response

from app.modules.ingestion.application.ports import (
    HostResolver,
    IngestionPipeline,
    IngestionScheduler,
    OnboardingStateStore,
)
from app.modules.ingestion.application.runner import SkeletonIngestionPipeline
from app.modules.ingestion.application.use_cases import (
    GetOnboardingState,
    StartUrlIngestion,
)
from app.core.logging import request_id_var, setup_logging
from app.modules.ingestion.infrastructure.resolver import SystemHostResolver
from app.modules.ingestion.infrastructure.scheduler import BackgroundTasksScheduler
from app.core.settings import Settings
from app.modules.ingestion.infrastructure.store import InMemoryOnboardingStateStore
from app.modules.ingestion.router import router as ingestion_router
from app.modules.scraping.cache import JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.llm import LLMProjectClassifier
from app.modules.scraping.router import router as scraping_router
from app.modules.scraping.service import PreScraperService

logger = logging.getLogger("orbit.ingestion")

SchedulerFactory = Callable[[BackgroundTasks], IngestionScheduler]

REQUEST_ID_HEADER = "X-Request-ID"


def _default_scheduler_factory(background_tasks: BackgroundTasks) -> IngestionScheduler:
    return BackgroundTasksScheduler(background_tasks)


def _default_pre_scraper(settings: Settings) -> PreScraperService:
    config = ScraperConfig.from_settings(settings)
    cache = JsonFilePrefetchCache.with_seed_file(
        settings.scraper_cache_dir,
        seed_path=settings.scraper_seed_file,
        ttl_seconds=settings.scraper_cache_ttl,
        seed_enabled=settings.scraper_seed_enabled,
    )
    classifier = None
    if settings.openrouter_api_key:
        classifier = LLMProjectClassifier(
            api_key=settings.openrouter_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
            max_tokens=settings.llm_max_tokens,
        )
    return PreScraperService(config=config, cache=cache, classifier=classifier)


def create_app(
    settings: Settings | None = None,
    resolver: HostResolver | None = None,
    store: OnboardingStateStore | None = None,
    pipeline: IngestionPipeline | None = None,
    scheduler_factory: SchedulerFactory | None = None,
    pre_scraper: PreScraperService | None = None,
) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.log_level)

    store = store or InMemoryOnboardingStateStore()
    resolver = resolver or SystemHostResolver()
    pipeline = pipeline or SkeletonIngestionPipeline(store)

    app = FastAPI(title="DataPeers ORBIT Agent")
    app.state.settings = settings
    app.state.onboarding_store = store
    app.state.start_ingestion = StartUrlIngestion(
        store=store, resolver=resolver, pipeline=pipeline
    )
    app.state.get_onboarding = GetOnboardingState(store=store)
    app.state.scheduler_factory = scheduler_factory or _default_scheduler_factory

    pre_scraper = pre_scraper or _default_pre_scraper(settings)
    app.state.pre_scraper = pre_scraper

    @app.middleware("http")
    async def correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return {"message": "Hello World"}

    @app.get("/hello/{name}")
    async def say_hello(name: str):
        return {"message": f"Hello {name}"}

    app.include_router(scraping_router, prefix="/api/v1")
    app.include_router(ingestion_router, prefix="/api/v1")

    logger.info("application_configured", extra={"app_env": settings.app_env})
    return app


app = create_app()
