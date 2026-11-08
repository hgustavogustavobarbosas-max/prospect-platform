"""Operacao comercial: mensagens humanas, proposta, aceite, briefing, previa, entrega, cobranca, sites."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.config import Settings
from app.models import (
    Briefing,
    Conversation,
    Interaction,
    Lead,
    Opportunity,
    Payment,
    Plan,
    Preview,
    Site,
    Subscription,
    Ticket,
)
from app.services import audit
from app.services.agent_guard import format_brl
from app.services.followups import aware
from app.services.lead_state import find_path
from app.services.outbox_svc import enqueue, notify_human
from app.services.site_check import check_site
from app.services.site_gen import render_site
from app.services.whatsapp import within_window

SYSTEM = Principal("system:crm", "service")


class CRMError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _now() -> datetime:
    return datetime.now(UTC)


def advance(db: Session, lead: Lead, target: str, who: Principal = SYSTEM) -> None:
    for step in find_path(lead.status, target) or []:
        previous, lead.status = lead.status, step
        audit.record(db, who, "transition", "leads", lead.id, {"from": previous, "to": step})


def last_inbound_at(db: Session, lead_id) -> datetime | None:
    return aware(
        db.scalar(
            select(func.max(Interaction.created_at)).where(
                Interaction.lead_id == lead_id, Interaction.direction == "in"
            )
        )
    )


# ---------- humano no atendimento ----------
def send_human_message(db: Session, lead: Lead, text: str, who: Principal, key: str | None = None) -> Interaction:
    if not within_window(last_inbound_at(db, lead.id), _now()):
        raise CRMError(409, "Janela de 24h fechada: o cliente precisa falar primeiro ou use um template aprovado.")
    out = Interaction(
        lead_id=lead.id, channel="whatsapp", direction="out", content=text,
        meta={"kind": "human", "by": who.subject}, created_at=_now(),
    )
    db.add(out)
    db.flush()
    enqueue(
        db, "send_whatsapp",
        {"lead_id": str(lead.id), "text": text, "kind": "human", "interaction_id": str(out.id)},
        key or f"human-{uuid.uuid4()}",
    )
    conv = db.scalar(
        select(Conversation).where(Conversation.lead_id == lead.id, Conversation.status.in_(["open", "handoff"]))
        .order_by(Conversation.created_at.desc()).limit(1)
    )
    if conv is not None:
        conv.status = "handoff"  # humano assumiu: o agente nao responde enquanto isso
    advance(db, lead, "handoff", who)
    return out


# ---------- proposta e aceite ----------
def _plan(db: Session, code: str) -> Plan | None:
    return db.scalar(select(Plan).where(Plan.code == code))


def price_text(plan: Plan | None, opp: Opportunity) -> str:
    cents = opp.value_cents if opp.value_cents is not None else (plan.price_cents if plan else None)
    return format_brl(cents) if cents is not None else "sob consulta"


def ensure_proposal(db: Session, settings: Settings, opp: Opportunity, client_name, notes) -> Opportunity:
    plan = _plan(db, opp.plan)
    if opp.value_cents is None and plan and plan.price_cents is not None:
        opp.value_cents = plan.price_cents
    if opp.proposal_token is None:
        opp.proposal_token = new_token()
    if opp.valid_until is None or aware(opp.valid_until) < _now():
        opp.valid_until = _now() + timedelta(days=settings.proposal_validity_days)
    if client_name is not None:
        opp.client_name = client_name
    if notes is not None:
        opp.proposal_notes = notes
    if opp.status == "draft":
        opp.status = "sent"
    return opp


def accept_proposal(db: Session, settings: Settings, opp: Opportunity) -> str:
    """Idempotente. Retorna 'accepted' | 'already' | 'expired'."""
    if opp.accepted_at is not None:
        return "already"
    if opp.status not in ("draft", "sent") or (opp.valid_until and aware(opp.valid_until) < _now()):
        return "expired"
    opp.status, opp.accepted_at, opp.accepted_via = "accepted", _now(), "link"
    lead = db.get(Lead, opp.lead_id)
    if lead is not None:
        advance(db, lead, "won")
    audit.record(db, SYSTEM, "accept", "opportunities", opp.id, {"via": "link"})
    notify_human(db, f"accepted-{opp.id}", "Proposta aceita pelo cliente!", kind="proposal_accepted",
                 opportunity_id=str(opp.id))
    kickoff(db, settings, opp)
    return "accepted"


def kickoff(db: Session, settings: Settings, opp: Opportunity) -> Briefing:
    """Idempotente: cria o briefing (link unico) e tenta enviar ao cliente; senao avisa a equipe."""
    brief = db.scalar(select(Briefing).where(Briefing.opportunity_id == opp.id))
    if brief is None:
        brief = Briefing(opportunity_id=opp.id, token=new_token(), status="pending")
        db.add(brief)
        db.flush()
    link = f"{settings.public_base_url}/public/briefing/{brief.token}"
    lead = db.get(Lead, opp.lead_id)
    sent = False
    if lead is not None and brief.status == "pending":
        try:
            send_human_message(
                db, lead, f"Obrigado por fechar conosco! Para montarmos seu site, preencha este formulario: {link}",
                SYSTEM, key=f"briefing-link-{opp.id}",
            )
            sent = True
        except CRMError:
            pass
    notify_human(
        db, f"kickoff-{opp.id}",
        "Inicio da entrega: briefing criado." + ("" if sent else f" Envie ao cliente: {link}"),
        kind="delivery_kickoff", opportunity_id=str(opp.id),
    )
    return brief


# ---------- previa e entrega ----------
def create_preview(db: Session, settings: Settings, opp: Opportunity) -> Preview:
    brief = db.scalar(select(Briefing).where(Briefing.opportunity_id == opp.id))
    if brief is None or brief.status != "submitted" or not brief.data:
        raise CRMError(409, "O cliente ainda nao enviou o briefing.")
    html = render_site(brief.data, preview=True)
    prev = Preview(
        opportunity_id=opp.id, token=new_token(), status="active", html=html,
        expires_at=_now() + timedelta(days=settings.preview_ttl_days),
    )
    db.add(prev)
    db.flush()
    return prev


def deliver(db: Session, opp: Opportunity, url: str, who: Principal) -> Site:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    opp.status, opp.delivered_at = "delivered", _now()
    site = Site(opportunity_id=opp.id, url=url, status="unknown", consecutive_failures=0)
    db.add(site)
    db.flush()
    audit.record(db, who, "deliver", "opportunities", opp.id)
    return site


def check_sites(db: Session, timeout: float = 5.0, http=None) -> dict:
    stats = {"checked": 0, "up": 0, "down": 0}
    for site in db.scalars(select(Site)).all():
        result = check_site(site.url, timeout=timeout, http=http)
        ok = result in ("site_ok", "unchecked")
        site.last_check_at = _now()
        stats["checked"] += 1
        if ok:
            if site.status == "down":
                notify_human(db, f"site-up-{site.id}-{_now():%Y%m%d%H}", f"Site voltou ao ar: {site.url}", kind="site_up")
            site.status, site.consecutive_failures = "up", 0
            stats["up"] += 1
        else:
            site.consecutive_failures += 1
            stats["down"] += 1
            if site.consecutive_failures >= 2:  # 2 falhas seguidas: evita alarme falso
                site.status = "down"
                notify_human(db, f"site-down-{site.id}-{_now():%Y%m%d}", f"Site fora do ar: {site.url}", kind="site_down")
    return stats


# ---------- cobranca ----------
def create_charge(db: Session, opp: Opportunity, amount_cents: int | None, due_days: int, provider: str) -> Payment:
    amount = amount_cents if amount_cents is not None else opp.value_cents
    if not amount:
        raise CRMError(422, "Defina o valor (amount_cents) ou o preco do plano.")
    key = f"opp-{opp.id}-setup"
    existing = db.scalar(select(Payment).where(Payment.idempotency_key == key))
    if existing:
        return existing
    pay = Payment(
        opportunity_id=opp.id, amount_cents=amount, provider=provider, status="pending",
        idempotency_key=key, due_at=_now() + timedelta(days=due_days),
    )
    db.add(pay)
    db.flush()
    return pay


def mark_paid(pay: Payment, ref: str | None = None) -> bool:
    """Idempotente: devolve True se mudou de estado agora."""
    if pay.status == "paid":
        return False
    pay.status, pay.paid_at = "paid", _now()
    if ref and not pay.provider_ref:
        pay.provider_ref = ref
    return True


def add_month(dt: datetime) -> datetime:
    return dt + timedelta(days=30)


def billing_run(db: Session) -> dict:
    now = _now()
    out = {"charges_created": 0, "overdue_notified": 0, "upsell_notified": 0}
    for sub in db.scalars(select(Subscription).where(Subscription.status == "active")).all():
        if aware(sub.next_billing_at) <= now:
            key = f"sub-{sub.id}-{aware(sub.next_billing_at):%Y%m}"
            if not db.scalar(select(Payment.id).where(Payment.idempotency_key == key)):
                db.add(Payment(
                    opportunity_id=sub.opportunity_id, amount_cents=sub.price_cents, provider="manual",
                    status="pending", idempotency_key=key, due_at=now + timedelta(days=5), subscription_id=sub.id,
                ))
                out["charges_created"] += 1
            sub.next_billing_at = add_month(aware(sub.next_billing_at))
    db.flush()
    for pay in db.scalars(select(Payment).where(Payment.status.in_(["pending", "overdue"]), Payment.due_at.is_not(None))).all():
        late = (now - aware(pay.due_at)).days
        if late >= 1:
            pay.status = "overdue"
            for bucket in (15, 5, 1):  # regua: 1, 5 e 15 dias de atraso
                if late >= bucket:
                    notify_human(db, f"overdue-{pay.id}-{bucket}", f"Pagamento em atraso ha {late} dia(s).",
                                 kind="overdue", payment_id=str(pay.id), days_late=late)
                    out["overdue_notified"] += 1
                    break
    cutoff = now - timedelta(days=30)
    for opp in db.scalars(select(Opportunity).where(Opportunity.status == "delivered", Opportunity.delivered_at < cutoff)).all():
        if not db.scalar(select(Subscription.id).where(Subscription.opportunity_id == opp.id)):
            notify_human(db, f"upsell-{opp.id}", "Cliente entregue ha 30+ dias sem plano recorrente: ofereca manutencao/catalogo.",
                         kind="upsell", opportunity_id=str(opp.id))
            out["upsell_notified"] += 1
    return out


def open_ticket_for_customer(db: Session, lead: Lead, text: str) -> None:
    if db.scalar(select(Ticket.id).where(Ticket.lead_id == lead.id, Ticket.status != "resolved", Ticket.deleted_at.is_(None))):
        return
    db.add(Ticket(lead_id=lead.id, subject="Mensagem de cliente (pos-venda)", body=text, status="open", priority="normal"))


# ---------- metricas, caixa de entrada, timeline ----------
def funnel(db: Session, days: int) -> dict:
    since = _now() - timedelta(days=days)

    def count(stmt):
        return db.scalar(stmt) or 0

    by_status = dict(db.execute(select(Lead.status, func.count(Lead.id)).where(Lead.deleted_at.is_(None)).group_by(Lead.status)).all())
    created = count(select(func.count(Lead.id)).where(Lead.created_at >= since, Lead.deleted_at.is_(None)))
    sent = count(select(func.count(Opportunity.id)).where(Opportunity.proposal_token.is_not(None), Opportunity.created_at >= since))
    accepted = count(select(func.count(Opportunity.id)).where(Opportunity.accepted_at >= since))
    revenue = db.scalar(select(func.coalesce(func.sum(Opportunity.value_cents), 0)).where(Opportunity.accepted_at >= since)) or 0
    from app.models import ApiUsage

    usage = db.execute(
        select(ApiUsage.provider, func.coalesce(func.sum(ApiUsage.calls), 0), func.coalesce(func.sum(ApiUsage.tokens), 0),
               func.coalesce(func.sum(ApiUsage.cost_micro_usd), 0)).where(ApiUsage.day >= since.date()).group_by(ApiUsage.provider)
    ).all()
    cost_micro = sum(int(r[3]) for r in usage)
    ai_cost = db.scalar(select(func.coalesce(func.sum(Conversation.cost_micro_usd), 0)).where(Conversation.created_at >= since)) or 0
    daily = db.execute(
        select(func.date(Lead.created_at), func.count(Lead.id)).where(Lead.created_at >= since, Lead.deleted_at.is_(None))
        .group_by(func.date(Lead.created_at)).order_by(func.date(Lead.created_at))
    ).all()
    won = by_status.get("won", 0)
    return {
        "period_days": days, "leads_by_status": by_status, "leads_created": created,
        "proposals_sent": sent, "proposals_accepted": accepted, "revenue_cents": int(revenue),
        "conv_lead_to_proposal": round(sent / created, 3) if created else None,
        "conv_proposal_to_accept": round(accepted / sent, 3) if sent else None,
        "usage": {r[0]: {"calls": int(r[1]), "tokens": int(r[2]), "cost_micro_usd": int(r[3])} for r in usage},
        "ai_cost_micro_usd": int(ai_cost), "api_cost_micro_usd": int(cost_micro),
        "cost_per_won_micro_usd": int((cost_micro + ai_cost) / won) if won else None,
        "leads_per_day": [{"day": str(d), "count": int(c)} for d, c in daily],
    }


def inbox(db: Session, sla_minutes: int) -> list[dict]:
    now = _now()
    rows = []
    for conv in db.scalars(select(Conversation).where(Conversation.status == "handoff", Conversation.deleted_at.is_(None))).all():
        last = db.scalar(select(Interaction).where(Interaction.lead_id == conv.lead_id).order_by(Interaction.created_at.desc()).limit(1))
        lead = db.get(Lead, conv.lead_id)
        waiting = last is not None and last.direction == "in"
        minutes = int((now - aware(last.created_at)).total_seconds() // 60) if last else 0
        rows.append({
            "conversation_id": str(conv.id), "lead_id": str(conv.lead_id), "tier": lead.tier if lead else None,
            "score": lead.score if lead else None, "waiting_for_human": waiting,
            "minutes_waiting": minutes if waiting else 0, "sla_breached": waiting and minutes > sla_minutes,
            "last_message": (last.content or "")[:140] if last else None,
        })
    rows.sort(key=lambda r: (not r["waiting_for_human"], -r["minutes_waiting"]))
    return rows


def timeline(db: Session, lead: Lead) -> dict:
    inter = db.scalars(select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at)).all()
    conv = db.scalar(select(Conversation).where(Conversation.lead_id == lead.id).order_by(Conversation.created_at.desc()).limit(1))
    opps = db.scalars(select(Opportunity).where(Opportunity.lead_id == lead.id, Opportunity.deleted_at.is_(None))).all()
    return {
        "interactions": [
            {"id": str(i.id), "direction": i.direction, "channel": i.channel, "content": i.content,
             "kind": (i.meta or {}).get("kind"), "delivery": (i.meta or {}).get("delivery"), "at": aware(i.created_at).isoformat()}
            for i in inter
        ],
        "conversation": None if conv is None else {
            "id": str(conv.id), "status": conv.status, "tokens_used": conv.tokens_used,
            "cost_micro_usd": conv.cost_micro_usd, "qualification": conv.qualification,
        },
        "opportunities": [{"id": str(o.id), "plan": o.plan, "status": o.status, "value_cents": o.value_cents} for o in opps],
    }


