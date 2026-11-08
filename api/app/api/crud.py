"""Fabrica de routers CRUD com soft delete, auditoria e erros consistentes."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, admin_only, reader, writer
from app.db.session import get_db
from app.services import audit


def build_crud_router(
    *,
    model: type,
    prefix: str,
    tag: str,
    create_schema: type,
    read_schema: type,
    update_schema: type | None = None,
    allow_delete: bool = True,
    filters: tuple[str, ...] = (),
    before_create: Callable[[dict], dict] | None = None,
    before_update: Callable[[dict, Any], dict] | None = None,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])
    entity = model.__tablename__
    soft = hasattr(model, "deleted_at")

    def get_or_404(db: Session, obj_id: uuid.UUID):
        obj = db.get(model, obj_id)
        if obj is None or (soft and obj.deleted_at is not None):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nao encontrado")
        return obj

    @router.get("", response_model=list[read_schema])
    def list_items(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        _: Principal = Depends(reader),
    ):
        stmt = select(model).order_by(model.created_at.desc()).limit(limit).offset(offset)
        if soft:
            stmt = stmt.where(model.deleted_at.is_(None))
        for name in filters:
            raw = request.query_params.get(name)
            if raw is None:
                continue
            col = getattr(model, name)
            try:
                value = uuid.UUID(raw) if isinstance(col.type, Uuid) else raw
            except ValueError:
                raise HTTPException(422, f"Filtro invalido: {name}") from None
            stmt = stmt.where(col == value)
        return db.scalars(stmt).all()

    @router.get("/{obj_id}", response_model=read_schema)
    def get_item(obj_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(reader)):
        return get_or_404(db, obj_id)

    @router.post("", response_model=read_schema, status_code=status.HTTP_201_CREATED)
    def create_item(payload: create_schema, db: Session = Depends(get_db), who: Principal = Depends(writer)):  # type: ignore[valid-type]
        data = payload.model_dump()
        if before_create:
            data = before_create(data)
        obj = model(**data)
        db.add(obj)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Registro duplicado ou referencia invalida") from None
        audit.record(db, who, "create", entity, obj.id)
        db.commit()
        db.refresh(obj)
        return obj

    if update_schema is not None:

        @router.patch("/{obj_id}", response_model=read_schema)
        def update_item(
            obj_id: uuid.UUID,
            payload: update_schema,  # type: ignore[valid-type]
            db: Session = Depends(get_db),
            who: Principal = Depends(writer),
        ):
            obj = get_or_404(db, obj_id)
            data = payload.model_dump(exclude_unset=True)
            if before_update:
                data = before_update(data, obj)
            for key, value in data.items():
                setattr(obj, key, value)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "Conflito com registro existente") from None
            audit.record(db, who, "update", entity, obj.id, {"fields": sorted(data)})
            db.commit()
            db.refresh(obj)
            return obj

    if allow_delete:

        @router.delete("/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
        def delete_item(
            obj_id: uuid.UUID, db: Session = Depends(get_db), who: Principal = Depends(admin_only)
        ):
            obj = get_or_404(db, obj_id)
            if soft:
                obj.deleted_at = datetime.now(UTC)
            else:
                db.delete(obj)
            audit.record(db, who, "delete", entity, obj_id)
            db.commit()

    return router
