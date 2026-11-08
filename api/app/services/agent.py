"""Agente comercial: orquestra classificacao, limites, LLM, guardrails, persistencia e handoff."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.config import Settings
from app.models import (
    Business,
    Consent,
    Contact,
    Conversation,
    Interaction,
    Lead,
    OutboxEvent,
    SuppressionEntry,
)
from app.services import audit
from app.services.agent_guard import (
    COMPLAINT_REPLY,
    FALLBACK_REPLY,
    HUMAN_REPLY,
    LGPD_REPLY,
    LIMIT_REPLY,
    MEDIA_REPLY,
    OPTOUT_REPLY,
    SAFE_REPLY,
    check_reply,
    classify_intent,
    finalize_reply,
    sanitize_input,
)
from app.services.agent_loop import build_history, run_llm
from app.services.agent_prompt import TOOL_DEFS, build_system_prompt, canary_for
from app.services.agent_tools import ToolContext, active_plans, execute_tool
from app.services.ai_scoring import AIError
from app.services.compliance import can_contact
from app.services.lead_state import find_path
from app.services.normalize import normalize_phone_br
from app.services.outbox_svc import enqueue, notify_human
from app.services.quota import QuotaExceeded, add_tokens, reserve_llm_request, tokens_available

log = structlog.get_logger()
AGENT = Principal("system:agent", "service")


@dataclass
class AgentResult:
    action: str
    reply: str | None = None
    conversation_id: object | None = None
    outbox_id: object | None = None
    flags: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def _advance(db: Session, lead: Lead, target: str) -> None:
    for step in find_path(lead.status, target) or []:
        previous, lead.status = lead.status, step
        audit.record(db, AGENT, "transition", "leads", lead.id, {"from": previous, "to": step})


def _conversation(db: Session, lead: Lead) -> Conversation:
    conv = db.scalar(
        select(Conversation)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.status.in_(["open", "handoff"]),
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    if conv is None:
        conv = Conversation(lead_id=lead.id, status="open", tokens_used=0, cost_micro_usd=0)
        db.add(conv)
        db.flush()
    return conv


def _outbound_count(db: Session, lead: Lead, since: datetime | None = None) -> int:
    stmt = select(func.count(Interaction.id)).where(
        Interaction.lead_id == lead.id, Interaction.direction == "out"
    )
    if since is not None:
        stmt = stmt.where(Interaction.created_at >= since)
    return db.scalar(stmt) or 0


def _history(db: Session, lead: Lead, limit: int) -> list[dict]:
    rows = db.execute(
        select(Interaction.direction, Interaction.content)
        .where(Interaction.lead_id == lead.id)
        .order_by(Interaction.created_at.desc())
        .limit(limit)
    ).all()
    wrapped = []
    for direction, content in reversed(rows):
        text = sanitize_input(content)
        wrapped.append((direction, f"<mensagem_do_cliente>{text}</mensagem_do_cliente>" if direction == "in" else text))
    return build_history(wrapped, limit)


def _send(
    db: Session, settings: Settings, lead: Lead, conv: Conversation, text: str,
    *, key: str, kind: str, tokens: int = 0, tools: list[str] | None = None,
) -> tuple[str, object]:
    first = _outbound_count(db, lead) == 0
    final = finalize_reply(text, agency=settings.agency_name, first_message=first)
    out = Interaction(
        lead_id=lead.id, channel="whatsapp", direction="out", content=final,
        meta={"kind": kind, "tokens": tokens, "tools": tools or []}, created_at=_now(),
    )
    db.add(out)
    db.flush()
    event = enqueue(
        db, "send_whatsapp",
        {
            "lead_id": str(lead.id), "conversation_id": str(conv.id), "text": final, "kind": kind,
            "interaction_id": str(out.id),
        },
        f"reply:{key}",
    )
    return final, event.id


def _handoff(
    db: Session, settings: Settings, lead: Lead, conv: Conversation, reason: str, *, key: str
) -> None:
    _advance(db, lead, "handoff")
    conv.status = "handoff"
    notify_human(
        db, f"handoff-{conv.id}", f"Atendimento humano necessario ({reason}).",
        kind="handoff", reason=reason, lead_id=str(lead.id), conversation_id=str(conv.id),
    )


def _optout(db: Session, lead: Lead, conv: Conversation, phone: str | None) -> list[str]:
    flags = []
    if phone:
        db.add(
            Consent(
                identifier=phone, channel="whatsapp", status="revoked", basis="opt_in",
                source="agent:optout", evidence="mensagem do titular", occurred_at=_now(),
            )
        )
        if not db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.identifier == phone)):
            db.add(SuppressionEntry(identifier=phone, reason="opt_out", source="agent"))
    else:
        flags.append("optout_sem_telefone")
        notify_human(
            db, f"optout-manual-{lead.id}", "Opt-out recebido sem telefone: suprimir manualmente.",
            kind="optout_manual", lead_id=str(lead.id),
        )
    _advance(db, lead, "suppressed")
    conv.status = "closed"
    return flags


def handle_inbound(
    db: Session, settings: Settings, llm, *, lead: Lead, text: str, external_id: str,
    message_type: str = "text", from_phone: str | None = None,
) -> AgentResult:
    clean = sanitize_input(text)
    conv = _conversation(db, lead)
    existing = db.scalar(select(Interaction).where(Interaction.external_id == external_id))
    if existing is not None:
        done = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == f"reply:{external_id}"))
        if done is not None:  # ja respondida: retry do n8n nao gera resposta duplicada
            return AgentResult(
                "duplicate", (done.payload or {}).get("text"), conv.id, done.id, ["duplicado"]
            )
        # salva mas ainda sem resposta (falha no meio): reprocessa com seguranca
    else:
        inbound = Interaction(
            lead_id=lead.id, channel="whatsapp", direction="in", content=clean or f"[{message_type}]",
            external_id=external_id, meta={"message_type": message_type}, created_at=_now(),
        )
        try:
            with db.begin_nested():
                db.add(inbound)
                db.flush()
        except IntegrityError:  # corrida entre duas entregas simultaneas
            return AgentResult("duplicate", conversation_id=conv.id)

    phone = normalize_phone_br(from_phone) if from_phone else None
    if phone and not db.scalar(
        select(Contact.id).where(
            Contact.business_id == lead.business_id, Contact.phone_e164 == phone,
            Contact.deleted_at.is_(None),
        )
    ):
        db.add(Contact(business_id=lead.business_id, phone=(from_phone or "")[:40], phone_e164=phone))
    db.commit()  # a mensagem recebida fica salva mesmo que algo falhe depois

    # 1) bloqueios: nunca responder a quem esta suprimido
    blocked = lead.status == "suppressed"
    if phone and not blocked:
        allowed, reason = can_contact(db, phone, "whatsapp")
        blocked = reason in ("suprimido", "consentimento_revogado")
    if blocked:
        return AgentResult("blocked", conversation_id=conv.id, flags=["suprimido"])
    if lead.status in ("won", "lost"):
        if lead.status == "won":  # cliente de pos-venda: abre chamado para a equipe
            from app.services.crm_ops import open_ticket_for_customer

            open_ticket_for_customer(db, lead, clean)
        _handoff(db, settings, lead, conv, "lead_encerrado", key=external_id)  # no-op no estado, notifica
        notify_human(db, f"closed-msg-{external_id}", "Mensagem de lead encerrado.", lead_id=str(lead.id))
        db.commit()
        return AgentResult("human_active", conversation_id=conv.id, flags=["lead_encerrado"])

    _advance(db, lead, "replying")

    # 2) classificacao deterministica ANTES do LLM
    intent = classify_intent(clean, message_type)
    fixed = {
        "optout": ("optout", OPTOUT_REPLY), "lgpd": ("handoff", LGPD_REPLY),
        "complaint": ("handoff", COMPLAINT_REPLY), "human": ("handoff", HUMAN_REPLY),
        "media": ("reply", MEDIA_REPLY),
    }
    if intent in fixed:
        action, reply_text = fixed[intent]
        flags = [f"intent:{intent}"]
        if intent == "optout":
            flags += _optout(db, lead, conv, phone)
        elif action == "handoff":
            _handoff(db, settings, lead, conv, intent, key=external_id)
        final, outbox_id = _send(db, settings, lead, conv, reply_text, key=external_id, kind=intent)
        db.commit()
        return AgentResult(action, final, conv.id, outbox_id, flags)

    # 3) atendimento humano ativo: o agente nao fala
    if conv.status == "handoff":
        notify_human(
            db, f"human-msg-{external_id}", "Nova mensagem em conversa com atendimento humano.",
            kind="human_message", lead_id=str(lead.id), conversation_id=str(conv.id),
        )
        db.commit()
        return AgentResult("human_active", conversation_id=conv.id)

    # 4) limites e disponibilidade -> handoff com mensagem fixa
    def fallback(reply_text: str, flag: str) -> AgentResult:
        _handoff(db, settings, lead, conv, flag, key=external_id)
        final, oid = _send(db, settings, lead, conv, reply_text, key=external_id, kind=flag)
        db.commit()
        return AgentResult("handoff", final, conv.id, oid, [flag])

    if not settings.agent_enabled or llm is None:
        return fallback(FALLBACK_REPLY, "agente_indisponivel")
    turns = _outbound_count(db, lead, since=conv.created_at)
    if turns >= settings.agent_max_turns or conv.tokens_used >= settings.agent_max_tokens_per_conversation:
        return fallback(LIMIT_REPLY, "limite_conversa")
    if not tokens_available(db, "llm", settings.llm_daily_token_limit):
        return fallback(LIMIT_REPLY, "limite_diario_tokens")

    # 5) LLM com ferramentas
    biz = db.get(Business, lead.business_id)
    card = {
        "segmento": biz.segment if biz else None, "regiao": biz.region if biz else None,
        "perfil": lead.tier, "situacao_do_site": biz.website_status if biz else None,
        "etapa_do_funil": lead.status, "dados_ja_coletados": conv.qualification,
    }
    canary = canary_for(settings.jwt_secret)
    system = build_system_prompt(agency=settings.agency_name, canary=canary, card=card)
    ctx = ToolContext(db=db, lead=lead, conv=conv, settings=settings)
    try:
        text_out, tokens, called = run_llm(
            llm, system=system, messages=_history(db, lead, settings.agent_history_messages),
            tools=TOOL_DEFS, execute=lambda n, a: execute_tool(ctx, n, a),
            max_iterations=3, max_tokens=400,
            before_request=lambda payload: reserve_llm_request(db, settings, payload),
        )
    except (AIError, QuotaExceeded) as exc:
        log.warning("agente_llm_falhou", error=str(exc))
        limited = isinstance(exc, QuotaExceeded)
        return fallback(LIMIT_REPLY if limited else FALLBACK_REPLY,
                        "limite_diario_tokens" if limited else "llm_erro")
    add_tokens(db, "llm", tokens)
    conv.tokens_used += tokens
    conv.cost_micro_usd += tokens * settings.llm_cost_micro_usd_per_1k_tokens // 1000

    # 6) guardrails de saida
    allowed_cents = {p.price_cents for p in active_plans(db) if p.price_cents is not None}
    hosts = {h.strip().lower() for h in settings.allowed_reply_hosts.split(",") if h.strip()}
    violations = check_reply(text_out, allowed_cents=allowed_cents, canary=canary, allowed_hosts=hosts)
    flags: list[str] = []
    if violations:
        log.warning("agente_resposta_bloqueada", violations=violations)
        flags.append("guard:" + ",".join(violations))
        text_out = SAFE_REPLY
        ctx.handoff_reason = ctx.handoff_reason or "outro"

    if ctx.handoff_reason:
        _handoff(db, settings, lead, conv, ctx.handoff_reason, key=external_id)
    final, outbox_id = _send(
        db, settings, lead, conv, text_out, key=external_id, kind="agent", tokens=tokens, tools=called,
    )
    db.commit()
    return AgentResult("handoff" if ctx.handoff_reason else "reply", final, conv.id, outbox_id, flags)

