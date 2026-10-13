"""Maps application errors to HTTP responses (Java ``RestExceptionHandler``); body is ``{"error": msg}``."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.application.domain.errors import (
    ConcurrencyError,
    DataConflictError,
    DomainStateError,
    DomainValidationError,
    NotFoundError,
)


class ApiError(Exception):
    """Raised by the web layer itself (auth, request checks) with an explicit status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_STATUS: dict[type[Exception], int] = {
    NotFoundError: 404,
    DomainStateError: 409,
    ConcurrencyError: 409,
    DataConflictError: 409,
    DomainValidationError: 400,
}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Validation failed"
    first = errors[0]
    loc = [str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path")]
    field = loc[-1] if loc else "request"
    msg = first.get("msg", "invalid").removeprefix("Value error, ")
    if first.get("type") == "missing":
        msg = "must not be null"
    return f"{field}: {msg}"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return _error(exc.status_code, exc.message)

    for error_type, status in _STATUS.items():

        async def _handler(_: Request, exc: Exception, status: int = status):
            return _error(status, str(exc))

        app.add_exception_handler(error_type, _handler)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return _error(400, _validation_message(exc))
