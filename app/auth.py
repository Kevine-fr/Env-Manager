"""Authentification admin : login par mot de passe + jeton JWT (Bearer).

Un seul rôle : admin. Seul lui peut lire/éditer/supprimer les secrets.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


def verify_credentials(username: str, password: str) -> bool:
    """Compare identifiants en temps constant (anti timing-attack)."""
    user_ok = hmac.compare_digest(
        (username or "").encode(), settings.admin_username.encode()
    )
    pass_ok = hmac.compare_digest(
        (password or "").encode(), settings.admin_password.encode()
    )
    return user_ok and pass_ok


def create_token() -> dict:
    """Génère un JWT signé valable `jwt_expire_hours`."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": settings.admin_username,
        "role": "admin",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_at": expire.isoformat()}


def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dépendance FastAPI : exige un jeton admin valide."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expirée, reconnectez-vous.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Jeton invalide."
        )
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Accès réservé à l'admin."
        )
    return payload
