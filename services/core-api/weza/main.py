"""WEZA Core API — FastAPI application factory."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import weza.consumers  # noqa: F401 — registers event consumers
import weza.domains.need.journey  # noqa: F401 — registers the customer journey graph
from weza.api.v1 import admin, auth, crb, customer, institution, public, staff, webhooks
from weza.config import get_settings
from weza.platform.context import correlation_id_var
from weza.platform.db import session_scope
from weza.platform.errors import install_error_handlers
from weza.platform.logging import configure_logging

log = logging.getLogger("weza.api")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    worker = None
    if getattr(app.state, "start_worker", False):
        from weza.worker import Worker
        worker = Worker()
        app.state.worker_thread = worker.start_thread()
    yield
    if worker:
        worker.stop()


def create_app(start_worker: bool | None = None) -> FastAPI:
    s = get_settings()
    configure_logging()
    if s.is_production and (problems := s.production_problems()):
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    log.info("channel_config", extra={"data": s.channel_config_summary()})  # names only, never values
    if s.whatsapp_required and (missing := s.whatsapp_missing):
        raise RuntimeError("WhatsApp is required but not configured: " + ", ".join(missing))
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
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers["Cache-Control"] = "no-store"
        if s.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        elapsed = int((time.monotonic() - started) * 1000)
        if elapsed > 2000:
            log.warning("slow_request", extra={"data": {"path": request.url.path, "ms": elapsed}})
        return response

    install_error_handlers(app)
    for r in (public.router, auth.router, customer.router, crb.router, institution.router, admin.router,
              staff.router, webhooks.router):
        app.include_router(r, prefix="/api/v1")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        # Render must check the database and the consumer that actually answers WhatsApp,
        # rather than marking an HTTP-only process healthy while messages accumulate.
        try:
            with session_scope() as db:
                db.execute(text("SELECT 1"))
                stale_whatsapp = db.execute(text(
                    "SELECT count(*) FROM notification.whatsapp_inbox "
                    "WHERE status='PENDING' AND received_at < now() - interval '5 minutes'"
                )).scalar_one()
        except Exception:  # noqa: BLE001 — never expose database connection details
            return JSONResponse({"status": "unavailable", "component": "database"}, status_code=503)
        if stale_whatsapp:
            return JSONResponse({"status": "unavailable", "component": "whatsapp_inbox",
                                 "stale_messages": int(stale_whatsapp)}, status_code=503)
        if app.state.start_worker:
            thread = getattr(app.state, "worker_thread", None)
            if thread is None or not thread.is_alive():
                return JSONResponse({"status": "unavailable", "component": "worker"}, status_code=503)
        if s.whatsapp_required and s.whatsapp_missing:
            return JSONResponse({"status": "unavailable", "component": "whatsapp"}, status_code=503)
        return {"status": "ok"}

    app.state.start_worker = s.run_worker_inprocess if start_worker is None else start_worker
    return app


app = create_app()
