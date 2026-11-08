"""API do CRM/dashboard e da operacao comercial (autenticada)."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.api.crud import build_crud_router
from app.api.deps import Principal, admin_only, reader, writer
from app.api.deps_clients import get_app_settings
from app.core.config import Settings
from app.core.webhook_security import verify_signature
from app.db.session import get_db
from app.models import Briefing, Lead, Opportunity, Payment, Plan, Site, Subscription, Ticket
from app.services import audit, crm_ops, privacy
from app.services.crm_ops import CRMError
from app.services.site_gen import build_package

router = APIRouter(tags=["crm"])
tickets_router = build_crud_router(
    model=Ticket, prefix="/tickets", tag="tickets", create_schema=s.TicketCreate,
    update_schema=s.TicketUpdate, read_schema=s.TicketRead, filters=("status", "lead_id", "opportunity_id"),
)


def _opp(db: Session, opp_id: uuid.UUID) -> Opportunity:
    opp = db.get(Opportunity, opp_id)
    if opp is None or opp.deleted_at is not None:
        raise HTTPException(404, "Oportunidade nao encontrada")
    return opp


def _lead(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.deleted_at is not None:
        raise HTTPException(404, "Lead nao encontrado")
    return lead


def _crm(fn):
    try:
        return fn()
    except CRMError as exc:
        raise HTTPException(exc.status, exc.message) from None


# ---------- painel ----------
@router.get("/metrics/funnel")
def metrics_funnel(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), _: Principal = Depends(reader)):
    return crm_ops.funnel(db, days)


@router.get("/inbox")
def inbox(db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings), _: Principal = Depends(reader)):
    return crm_ops.inbox(db, settings.human_sla_minutes)


@router.get("/leads/{lead_id}/timeline")
def lead_timeline(lead_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(reader)):
    return crm_ops.timeline(db, _lead(db, lead_id))


@router.post("/leads/{lead_id}/messages", status_code=202)
def human_message(
    lead_id: uuid.UUID, body: s.MessageIn, db: Session = Depends(get_db), who: Principal = Depends(writer),
    idempotency_key: str | None = Header(default=None),
):
    """Mensagem de um atendente (fica na fila de envio; so dentro da janela de 24h)."""
    lead = _lead(db, lead_id)
    _crm(lambda: crm_ops.send_human_message(db, lead, body.text, who, key=f"human-{idempotency_key}" if idempotency_key else None))
    audit.record(db, who, "message", "leads", lead.id, {"kind": "human"})
    db.commit()
    return {"queued": True}


@router.post("/conversations/{conv_id}/return-to-agent")
def return_to_agent(conv_id: uuid.UUID, db: Session = Depends(get_db), who: Principal = Depends(writer)):
    from app.models import Conversation

    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(404, "Nao encontrada")
    conv.status = "open"
    audit.record(db, who, "return_to_agent", "conversations", conv.id)
    db.commit()
    return {"status": conv.status}


# ---------- proposta / fechamento ----------
@router.post("/opportunities/{opp_id}/proposal", response_model=s.ProposalOut)
def make_proposal(
    opp_id: uuid.UUID, body: s.ProposalIn, db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings), who: Principal = Depends(writer),
):
    opp = crm_ops.ensure_proposal(db, settings, _opp(db, opp_id), body.client_name, body.notes)
    audit.record(db, who, "proposal", "opportunities", opp.id)
    db.commit()
    base = f"{settings.public_base_url}/public/proposals/{opp.proposal_token}"
    return s.ProposalOut(url=base, pdf_url=base + ".pdf", valid_until=opp.valid_until)


@router.post("/opportunities/{opp_id}/send-proposal", status_code=202)
def send_proposal(
    opp_id: uuid.UUID, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings),
    who: Principal = Depends(writer),
):
    opp = _opp(db, opp_id)
    if not opp.proposal_token:
        raise HTTPException(409, "Gere a proposta antes de enviar")
    lead = _lead(db, opp.lead_id)
    link = f"{settings.public_base_url}/public/proposals/{opp.proposal_token}"
    _crm(lambda: crm_ops.send_human_message(db, lead, f"Segue a sua proposta: {link}", who, key=f"proposal-link-{opp.id}"))
    db.commit()
    return {"queued": True, "url": link}


@router.post("/opportunities/{opp_id}/kickoff")
def kickoff(opp_id: uuid.UUID, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings),
            _: Principal = Depends(writer)):
    opp = _opp(db, opp_id)
    brief = crm_ops.kickoff(db, settings, opp)
    db.commit()
    return {"briefing_url": f"{settings.public_base_url}/public/briefing/{brief.token}", "status": brief.status}


@router.post("/opportunities/{opp_id}/preview")
def make_preview(opp_id: uuid.UUID, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings),
                 _: Principal = Depends(writer)):
    prev = _crm(lambda: crm_ops.create_preview(db, settings, _opp(db, opp_id)))
    db.commit()
    return {"url": f"{settings.public_base_url}/public/preview/{prev.token}", "expires_at": prev.expires_at}


@router.get("/opportunities/{opp_id}/site-package")
def site_package(opp_id: uuid.UUID, domain: str | None = Query(default=None, max_length=200),
                 db: Session = Depends(get_db), _: Principal = Depends(writer)):
    """Repositorio base do site final (ZIP): HTML + SEO + Lighthouse CI + guia de deploy."""
    opp = _opp(db, opp_id)
    brief = db.scalar(select(Briefing).where(Briefing.opportunity_id == opp.id))
    if brief is None or brief.status != "submitted" or not brief.data:
        raise HTTPException(409, "O cliente ainda nao enviou o briefing.")
    return Response(build_package(brief.data, domain=domain), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="site-{opp.id}.zip"'})


@router.post("/opportunities/{opp_id}/deliver", response_model=s.SiteRead)
def deliver(opp_id: uuid.UUID, body: s.DeliverIn, db: Session = Depends(get_db), who: Principal = Depends(writer)):
    opp = _opp(db, opp_id)
    if opp.accepted_at is None:
        raise HTTPException(409, "Proposta ainda nao aceita")
    site = crm_ops.deliver(db, opp, body.url, who)
    from app.services.outbox_svc import notify_human

    notify_human(db, f"nps-{opp.id}", "Site entregue. Envie ao cliente o link de avaliacao (NPS): "
                 f"/public/nps/{opp.proposal_token}", kind="delivered", opportunity_id=str(opp.id))
    db.commit()
    return site


# ---------- pagamentos e recorrencia ----------
@router.post("/opportunities/{opp_id}/charge", response_model=s.PaymentRead, status_code=201)
def charge(opp_id: uuid.UUID, body: s.ChargeIn, db: Session = Depends(get_db), who: Principal = Depends(writer)):
    pay = _crm(lambda: crm_ops.create_charge(db, _opp(db, opp_id), body.amount_cents, body.due_in_days, body.provider))
    audit.record(db, who, "charge", "payments", pay.id)
    db.commit()
    return pay


@router.post("/payments/{payment_id}/mark-paid", response_model=s.PaymentRead)
def mark_paid(payment_id: uuid.UUID, db: Session = Depends(get_db), who: Principal = Depends(writer)):
    pay = db.get(Payment, payment_id)
    if pay is None:
        raise HTTPException(404, "Nao encontrado")
    if crm_ops.mark_paid(pay):
        audit.record(db, who, "mark_paid", "payments", pay.id)
    db.commit()
    return pay


@router.post("/payments/webhook/{provider}")
async def payment_webhook(provider: str, request: Request, db: Session = Depends(get_db),
                          settings: Settings = Depends(get_app_settings)):
    """Webhook generico de provedor de pagamento (HMAC no corpo bruto). Idempotente por provider_ref."""
    import json

    raw = await request.body()
    if not settings.payment_webhook_secret:
        raise HTTPException(503, "PAYMENT_WEBHOOK_SECRET nao configurado")
    if not verify_signature(raw, request.headers.get("x-signature"), settings.payment_webhook_secret):
        raise HTTPException(401, "Assinatura invalida")
    try:
        data = json.loads(raw)
        ref, status = str(data["provider_ref"]), data["status"]
    except (ValueError, KeyError):
        raise HTTPException(400, "Corpo invalido (esperado: provider_ref e status)") from None
    pay = db.scalar(select(Payment).where(Payment.provider_ref == ref, Payment.provider == provider))
    if pay is None:
        raise HTTPException(404, "Pagamento nao encontrado")
    if status == "paid":
        crm_ops.mark_paid(pay)
    elif status in ("failed", "refunded"):
        pay.status = status
    db.commit()
    return {"ok": True}


@router.post("/opportunities/{opp_id}/subscriptions", response_model=s.SubscriptionRead, status_code=201)
def subscribe(opp_id: uuid.UUID, body: s.SubscriptionIn, db: Session = Depends(get_db), who: Principal = Depends(writer)):
    from datetime import UTC, datetime, timedelta

    opp = _opp(db, opp_id)
    price = body.price_cents
    if price is None:
        plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
        price = plan.price_cents if plan else None
    if not price:
        raise HTTPException(422, "Defina price_cents ou o preco do plano recorrente")
    sub = Subscription(opportunity_id=opp.id, plan_code=body.plan_code, price_cents=price,
                       status="active", next_billing_at=datetime.now(UTC) + timedelta(days=30))
    db.add(sub)
    db.flush()
    audit.record(db, who, "create", "subscriptions", sub.id)
    db.commit()
    return sub


@router.post("/billing/run")
def billing_run(db: Session = Depends(get_db), _: Principal = Depends(writer)):
    out = crm_ops.billing_run(db)
    db.commit()
    return out


# ---------- sites ----------
@router.get("/sites", response_model=list[s.SiteRead])
def list_sites(db: Session = Depends(get_db), _: Principal = Depends(reader)):
    return db.scalars(select(Site).order_by(Site.created_at.desc())).all()


@router.post("/sites/check")
def check_sites(db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings),
                _: Principal = Depends(writer)):
    out = crm_ops.check_sites(db, settings.site_check_timeout)
    db.commit()
    return out


# ---------- privacidade (LGPD) ----------
@router.get("/privacy/export")
def privacy_export(identifier: str = Query(...), db: Session = Depends(get_db), who: Principal = Depends(admin_only)):
    try:
        data = privacy.export_data(db, identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    audit.record(db, who, "export", "privacy", "titular")
    db.commit()
    return data


@router.post("/privacy/erase")
def privacy_erase(body: s.EraseIn, db: Session = Depends(get_db), who: Principal = Depends(admin_only)):
    if not body.confirm:
        raise HTTPException(422, "Envie confirm=true para apagar")
    try:
        out = privacy.erase_data(db, body.identifier, who)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return out
