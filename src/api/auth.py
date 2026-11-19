"""Constant-time X-API-Key authentication dependency."""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from api.dependencies import get_configured_api_key

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    provided_key: Annotated[str | None, Security(API_KEY_HEADER)],
    expected_key: Annotated[str, Depends(get_configured_api_key)],
) -> None:
    """Validate X-API-Key against API_KEY in constant time."""
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el encabezado X-API-Key.",
        )
    if not hmac.compare_digest(
        provided_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clave de API inválida.",
        )
