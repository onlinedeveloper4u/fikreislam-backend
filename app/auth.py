"""
FastAPI API security dependency.

Uses a shared secret (API_SECRET_KEY) passed as a Bearer token to
authenticate requests from the Next.js frontend.
"""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

security = HTTPBearer()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """Validate the Bearer token matches our API secret."""
    if not settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_SECRET_KEY not configured on the server",
        )
    if credentials.credentials != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return credentials.credentials
