from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, admin_only, get_principal
from app.api.deps_clients import get_app_settings
from app.api.limits import get_limiter
from app.core.config import Settings
from app.core.ratelimit import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas import LoginIn, TokenOut, UserCreate, UserRead
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

# hash descartavel para igualar o tempo de resposta quando o usuario nao existe
_DUMMY_HASH = hash_password("dummy-password-for-timing")


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit("login", 10, 60))])
def login(body: LoginIn, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings)):
    if settings.rate_limit_enabled:  # trava por e-mail: 10 tentativas / 15 min, mesmo vindo de IPs diferentes
        ok, _ = get_limiter(settings).allow(f"rl:login-email:{body.email.lower()}", 10, 900)
        if not ok:
            raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.", headers={"Retry-After": "900"})
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    ok = verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email ou senha invalidos")
    return TokenOut(access_token=create_access_token(str(user.id), user.role))


@router.get("/me")
def me(who: Principal = Depends(get_principal)):
    return {"subject": who.subject, "role": who.role}


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), who: Principal = Depends(admin_only)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(409, "Email ja cadastrado")
    user = User(email=email, hashed_password=hash_password(body.password), role=body.role)
    db.add(user)
    db.flush()
    audit.record(db, who, "create", "users", user.id)
    db.commit()
    db.refresh(user)
    return user
