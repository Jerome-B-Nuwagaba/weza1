"""WEZA Core API — FastAPI application factory."""

import logging
import time
import uuid

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
_worker = None


def create_app(start_worker: bool | None = None) -> FastAPI:
    s = get_settings()
    configure_logging()
    if s.is_production and ("local-dev" in s.secret_key or "bG9jYWwtZGV2" in s.vault_master_key):
        raise RuntimeError("Refusing to start in production with development secrets.")
    app = FastAPI(title="WEZA Core API", version="1.0.0",
                  description="Intelligent financial marketplace — zero core-system integration.",
                  docs_url=None if s.is_production else "/docs", openapi_url="/api/v1/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Correlation-ID"])

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

    should_start = s.run_worker_inprocess if start_worker is None else start_worker
    if should_start:
        @app.on_event("startup")
        def _start_worker():
            global _worker
            from weza.worker import Worker
            _worker = Worker()
            _worker.start_thread()

        @app.on_event("shutdown")
        def _stop_worker():
            if _worker:
                _worker.stop()
    return app


app = create_app()
