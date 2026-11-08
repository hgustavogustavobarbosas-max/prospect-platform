from fastapi import APIRouter

from app.api.routes import auth, compliance, crm, entities, ops, outbox, prospecting, whatsapp

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
for r in entities.routers:
    api_router.include_router(r)
api_router.include_router(compliance.router)
api_router.include_router(outbox.router)
api_router.include_router(prospecting.router)
api_router.include_router(ops.plans_router)
api_router.include_router(ops.router)
api_router.include_router(crm.router)
api_router.include_router(crm.tickets_router)
api_router.include_router(whatsapp.router)
