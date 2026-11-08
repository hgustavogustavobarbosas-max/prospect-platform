import hmac
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str  # admin | operator | service


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    if x_api_key:
        if hmac.compare_digest(x_api_key, get_settings().service_api_key):
            return Principal("service:n8n", "service")
        raise _unauthorized("API key invalida")
    if creds is None:
        raise _unauthorized("Credenciais ausentes")
    try:
        payload = decode_access_token(creds.credentials)
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _unauthorized("Token invalido ou expirado") from None
    if user is None or not user.is_active:
        raise _unauthorized("Usuario inativo")
    return Principal(user.email, user.role)


def require_roles(*roles: str):
    def checker(who: Principal = Depends(get_principal)) -> Principal:
        if who.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sem permissao")
        return who

    return checker


reader = require_roles("admin", "operator", "service")
writer = require_roles("admin", "operator", "service")
admin_only = require_roles("admin")
