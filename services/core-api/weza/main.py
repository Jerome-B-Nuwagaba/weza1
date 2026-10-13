"""WEZA Core API — FastAPI application factory."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import weza.consumers  # noqa: F401 — registers event consumers
import weza.domains.need.journey  # noqa: F401 — registers the customer journey graph
from weza.api.v1 import admin, auth, customer, institution, public
from weza.config import get_settings
from weza.platform.context import correlation_id_var
from weza.platform.errors import install_error_handlers
from weza.platform.logging import configure_logging

log = logging.getLogger("weza.api")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    worker = None
    if getattr(app.state, "start_worker", False):
        from weza.worker import Worker
        worker = Worker()
        worker.start_thread()
    yield
    if worker:
        worker.stop()


def create_app(start_worker: bool | None = None) -> FastAPI:
    s = get_settings()
    configure_logging()
    if s.is_production and ("local-dev" in s.secret_key or "bG9jYWwtZGV2" in s.vault_master_key):
        raise RuntimeError("Refusing to start in production with development secrets.")
    log.info("channel_config", extra={"data": s.channel_config_summary()})  # names only, never values
    app = FastAPI(title="WEZA Core API", version="1.0.0", lifespan=_lifespan,
                  description="Intelligent financial marketplace — zero core-system integration.",
                  docs_url=None if s.is_production else "/docs", openapi_url="/api/v1/openapi.json")
    origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    if origins == ["*"]:
        # Bearer-token clients only (Flutter web): any origin, but never with cookies.
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"],
                           allow_headers=["*"], expose_headers=["X-Correlation-ID"])
    else:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"],
                           allow_headers=["*"], expose_headers=["X-Correlation-ID"])

    @app.middleware("http")
    async def context_and_headers(request: Request, call_next):
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        token = correlation_id_var.set(cid[:64])
        started = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Correlation-ID"] = cid[:64]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        if s.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        elapsed = int((time.monotonic() - started) * 1000)
        if elapsed > 2000:
            log.warning("slow_request", extra={"data": {"path": request.url.path, "ms": elapsed}})
        return response

    install_error_handlers(app)
    for r in (public.router, auth.router, customer.router, institution.router, admin.router):
        app.include_router(r, prefix="/api/v1")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.state.start_worker = s.run_worker_inprocess if start_worker is None else start_worker
    return app


app = create_app()
