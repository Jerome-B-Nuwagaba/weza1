"""Common API error contract (TSD §59)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from weza.platform.context import correlation_id

log = logging.getLogger("weza.errors")


class WezaError(Exception):
    status = 400
    code = "BAD_REQUEST"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None,
                 details: list[dict[str, Any]] | None = None, retryable: bool | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        if retryable is not None:
            self.retryable = retryable
        self.details = details or []


class NotFound(WezaError):
    status = 404
    code = "NOT_FOUND"


class Forbidden(WezaError):
    status = 403
    code = "FORBIDDEN"


class Unauthorized(WezaError):
    status = 401
    code = "UNAUTHENTICATED"


class Conflict(WezaError):
    status = 409
    code = "CONFLICT"


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"


class ValidationFailed(WezaError):
    status = 422
    code = "VALIDATION_FAILED"


class RateLimited(WezaError):
    status = 429
    code = "RATE_LIMITED"
    retryable = True


def _body(code: str, message: str, retryable: bool, details: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "correlation_id": correlation_id(),
                      "retryable": retryable, "details": details or []}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(WezaError)
    async def _weza(_: Request, exc: WezaError):
        headers = {"Retry-After": "60"} if exc.status == 429 else None
        return JSONResponse(_body(exc.code, exc.message, exc.retryable, exc.details), status_code=exc.status,
                            headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "issue": e.get("msg", "")}
                   for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_FAILED", "Some fields are invalid.", False, details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHENTICATED", 403: "FORBIDDEN"}.get(
            exc.status_code, "HTTP_ERROR")
        return JSONResponse(_body(code, str(exc.detail), False), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled_error", exc_info=exc)
        return JSONResponse(_body("INTERNAL_ERROR", "Something went wrong. Please try again.", True),
                            status_code=500)
