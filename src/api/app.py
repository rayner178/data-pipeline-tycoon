"""FastAPI application factory and exception handlers."""

from collections.abc import Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response

from api.routers import api_router, health_router
from api.schemas import ErrorResponse
from application.errors import (
    ChallengeNotFound,
    EmptySubmission,
    EvaluatorUnavailable,
)


def _error_handler(
    status_code: int, detail: str
) -> Callable[[Request, Exception], Response]:
    def _handle(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(detail=detail).model_dump(),
        )

    return _handle


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Data Pipeline Tycoon API",
        description="Backend para validar retos de ingeniería de datos desde Roblox.",
        version="0.1.0",
    )
    application.add_exception_handler(
        EmptySubmission,
        _error_handler(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "La consulta SQL no puede estar vacía.",
        ),
    )
    application.add_exception_handler(
        ChallengeNotFound,
        _error_handler(
            status.HTTP_404_NOT_FOUND,
            "Reto no encontrado.",
        ),
    )
    application.add_exception_handler(
        EvaluatorUnavailable,
        _error_handler(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "El evaluador no está disponible en este momento. Intenta de nuevo.",
        ),
    )
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
