"""
Structured error handling — custom exceptions + FastAPI error handler.
Port of 4th-devs/01_05_agent errors/index.ts.

Response envelope: {"data": ..., "error": {"message": "...", "details": ...}}
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base application error with HTTP status code."""

    def __init__(self, message: str, status_code: int = 500, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class ValidationError(AppError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message, 400, details)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found"):
        super().__init__(message, 404)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, 401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, 403)


class RateLimitedError(AppError):
    def __init__(self, message: str = "Too many requests", retry_after: int | None = None):
        super().__init__(message, 429)
        self.retry_after = retry_after


class PayloadTooLargeError(AppError):
    def __init__(self, message: str = "Request too large"):
        super().__init__(message, 413)


# ── Error factory (mirrors TS `err` object) ──────────────────────────────────

class _ErrFactory:
    @staticmethod
    def validation(msg: str, details: Any = None) -> ValidationError:
        return ValidationError(msg, details)

    @staticmethod
    def not_found(msg: str = "Not found") -> NotFoundError:
        return NotFoundError(msg)

    @staticmethod
    def unauthorized(msg: str = "Unauthorized") -> UnauthorizedError:
        return UnauthorizedError(msg)

    @staticmethod
    def forbidden(msg: str = "Forbidden") -> ForbiddenError:
        return ForbiddenError(msg)

    @staticmethod
    def rate_limited(msg: str = "Too many requests", retry_after: int | None = None) -> RateLimitedError:
        return RateLimitedError(msg, retry_after)

    @staticmethod
    def payload_too_large(msg: str = "Request too large") -> PayloadTooLargeError:
        return PayloadTooLargeError(msg)

    @staticmethod
    def internal(msg: str = "Internal server error") -> AppError:
        return AppError(msg, 500)


err = _ErrFactory()


# ── FastAPI integration ──────────────────────────────────────────────────────

def register_error_handlers(app: FastAPI) -> None:
    """Register structured error handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        body: dict[str, Any] = {
            "data": None,
            "error": {"message": exc.message},
        }
        if exc.details is not None:
            body["error"]["details"] = exc.details
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitedError) and exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=headers or None,
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        from infra.logger import logger
        logger.error(f"Unhandled: {exc}", error=str(exc), path=str(request.url))
        return JSONResponse(
            status_code=500,
            content={"data": None, "error": {"message": "Internal server error"}},
        )
