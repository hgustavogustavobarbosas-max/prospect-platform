"""Ferramentas do agente. Todas atuam SOMENTE no lead/conversa do contexto (nunca em IDs vindos do modelo)."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Conversation, Lead, Opportunity, Plan
from app.services.agent_guard import format_brl, sanitize_input

HANDOFF_REASONS = {"negociacao", "duvida_tecnica", "reclamacao", "pronto_para_fechar", "outro"}
PLAN_CODES = {"basic", "professional", "custom"}
INTERESTS = PLAN_CODES | {"indefinido"}


@dataclass
class ToolContext:
    db: Session
    lead: Lead
    conv: Conversation
    settings: Settings
    handoff_reason: str | None = None
    proposal_id: str | None = None
    notes: list[str] = field(default_factory=list)


def active_plans(db: Session) -> list[Plan]:
    return list(db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.code)).all())


def _get_plans(ctx: ToolContext, _args: dict) -> dict:
    return {
        "planos": [
            {
                "codigo": p.code,
                "nome": p.name,
                "descricao": p.description,
                "itens": p.features or [],
                "preco": format_brl(p.price_cents) if p.price_cents is not None else "sob consulta",
            }
            for p in active_plans(ctx.db)
        ]
    }


def _record_qualification(ctx: ToolContext, args: dict) -> dict:
    data = dict(ctx.conv.qualification or {})
    interesse = args.get("interesse")
    if interesse in INTERESTS:
        data["interesse"] = interesse
    for key in ("nome_contato", "melhor_horario", "objetivo"):
        if isinstance(args.get(key), str) and args[key].strip():
            data[key] = sanitize_input(args[key], 200)
    if isinstance(args.get("tem_site"), bool):
        data["tem_site"] = args["tem_site"]
    ctx.conv.qualification = data  # reatribui: o SQLAlchemy nao detecta mutacao in-place de JSON
    return {"ok": True}


def _request_handoff(ctx: ToolContext, args: dict) -> dict:
    reason = args.get("motivo")
    ctx.handoff_reason = reason if reason in HANDOFF_REASONS else "outro"
    return {"ok": True, "mensagem": "Um atendente sera acionado. Avise o cliente."}


def _create_proposal_request(ctx: ToolContext, args: dict) -> dict:
    code = args.get("plano")
    if code not in PLAN_CODES:
        return {"ok": False, "erro": "plano_invalido"}
    plan = ctx.db.scalar(select(Plan).where(Plan.code == code, Plan.active.is_(True)))
    if plan is None:
        return {"ok": False, "erro": "plano_indisponivel"}
    existing = ctx.db.scalar(
        select(Opportunity).where(
            Opportunity.lead_id == ctx.lead.id,
            Opportunity.plan == code,
            Opportunity.status == "draft",
            Opportunity.deleted_at.is_(None),
        )
    )
    opp = existing
    if opp is None:
        opp = Opportunity(lead_id=ctx.lead.id, plan=code, value_cents=plan.price_cents, status="draft")
        ctx.db.add(opp)
        ctx.db.flush()
    ctx.proposal_id = str(opp.id)
    ctx.handoff_reason = ctx.handoff_reason or "pronto_para_fechar"
    return {"ok": True, "mensagem": "Rascunho de proposta criado; um atendente envia os detalhes."}


_TOOLS = {
    "get_plans": _get_plans,
    "record_qualification": _record_qualification,
    "request_handoff": _request_handoff,
    "create_proposal_request": _create_proposal_request,
}


def execute_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    fn = _TOOLS.get(name)
    if fn is None:
        return {"ok": False, "erro": "ferramenta_desconhecida"}
    try:
        return fn(ctx, args if isinstance(args, dict) else {})
    except Exception:  # noqa: BLE001 - a falha de uma ferramenta nao pode derrubar a conversa
        return {"ok": False, "erro": "falha_interna"}
