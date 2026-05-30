"""
ATRBA Resources Hub — Authentication Service
Session-based auth reusing the existing admin_users + admin_sessions tables.
"""

import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt

_supabase = None

def init_auth(supabase_client):
    global _supabase
    _supabase = supabase_client

def get_client():
    if _supabase is None:
        raise RuntimeError("Auth service not initialised")
    return _supabase


SESSION_HOURS = 24
bearer_scheme = HTTPBearer(
    scheme_name="Admin Bearer Token",
    description="Token from POST /resources/admin/login",
    auto_error=True,
)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_session(admin_id: str) -> dict:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    get_client().table("admin_sessions").insert({
        "admin_id":   admin_id,
        "token":      token,
        "expires_at": expires_at.isoformat(),
    }).execute()
    return {"token": token, "expires_at": expires_at.isoformat()}


async def get_admin_session(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """FastAPI dependency — validates Bearer token on every admin request."""
    token = credentials.credentials
    try:
        result = (
            get_client().table("admin_sessions")
            .select("*, admin_users(*)")
            .eq("token", token)
            .gte("expires_at", datetime.now(timezone.utc).isoformat())
            .single()
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Auth DB error: {exc}")

    if not result.data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return result.data