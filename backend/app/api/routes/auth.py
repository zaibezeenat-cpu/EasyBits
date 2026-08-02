"""
Login endpoint.

Rate limited because a single shared secret is the only thing standing between
the internet and a service-role database connection: without a limit, the secret
is brute-forceable at network speed.
"""
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import create_access_token, verify_shared_secret

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


class LoginRequest(BaseModel):
    secret: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(request: Request, payload: LoginRequest) -> LoginResponse:
    """
    Exchanges the shared secret for a short-lived bearer token.

    The failure response is deliberately generic and identical for "no secret
    configured" and "wrong secret" -- distinguishing them would tell an attacker
    whether the deployment is unconfigured.
    """
    if not verify_shared_secret(payload.secret):
        logger.warning(f"Failed login attempt from {get_remote_address(request)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token, expires_in = create_access_token()
    return LoginResponse(access_token=token, expires_in=expires_in)
