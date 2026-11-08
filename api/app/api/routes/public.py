"""Paginas publicas por link com token (cliente final): proposta, aceite, briefing, previa, NPS."""

from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_clients import get_app_settings
from app.core.config import Settings
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.models import Briefing, Opportunity, Plan, Preview
from app.services import crm_ops, public_pages as pg
from app.services.agent_guard import sanitize_input
from app.services.followups import aware
from app.services.outbox_svc import notify_human
from app.services.proposal_pdf import render_proposal_pdf

router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(rate_limit("public", 60, 60))])
MAX_FORM = 20_000
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _html(content: str, status: int = 200, extra: dict | None = None) -> HTMLResponse:
    return HTMLResponse(content, status_code=status, headers={**HEADERS, **(extra or {})})


async def _form(request: Request) -> dict[str, str]:
    raw = await request.body()
    if len(raw) > MAX_FORM:
        raise HTTPException(413, "Formulario grande demais")
    return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}


def _opp_by_token(db: Session, token: str) -> Opportunity | None:
    return db.scalar(select(Opportunity).where(Opportunity.proposal_token == token))


def _proposal_context(db: Session, settings: Settings, opp: Opportunity) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == opp.plan))
    expired = opp.accepted_at is None and (
        opp.status in ("expired", "rejected") or (opp.valid_until is not None and aware(opp.valid_until) < datetime.now(UTC))
    )
    base = f"/public/proposals/{opp.proposal_token}"
    return dict(
        agency=settings.agency_name, plan_name=plan.name if plan else opp.plan,
        features=(plan.features if plan and plan.features else []), plan=plan,
        price_text=crm_ops.price_text(plan, opp), expired=expired, base=base,
        valid_until=aware(opp.valid_until).strftime("%d/%m/%Y") if opp.valid_until else "-",
    )


@router.get("/proposals/{token}.pdf")
def proposal_pdf(token: str, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings)):
    opp = _opp_by_token(db, token)
    if opp is None:
        raise HTTPException(404, "Proposta nao encontrada")
    c = _proposal_context(db, settings, opp)
    pdf = render_proposal_pdf(
        agency=c["agency"], client_name=opp.client_name, plan_name=c["plan_name"],
        plan_description=c["plan"].description if c["plan"] else None, features=c["features"],
        price_text=c["price_text"], valid_until=c["valid_until"],
        accept_url=f"{settings.public_base_url}{c['base']}", notes=opp.proposal_notes,
    )
    return Response(pdf, media_type="application/pdf", headers={**HEADERS, "Content-Disposition": 'inline; filename="proposta.pdf"'})


@router.get("/proposals/{token}")
def proposal_page(token: str, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings)):
    opp = _opp_by_token(db, token)
    if opp is None:
        return _html(pg.gone_page("Proposta nao encontrada."), 404)
    c = _proposal_context(db, settings, opp)
    return _html(pg.proposal_page(
        agency=c["agency"], plan_name=c["plan_name"], price_text=c["price_text"], valid_until=c["valid_until"],
        features=c["features"], pdf_url=c["base"] + ".pdf", accept_url=c["base"] + "/accept",
        accepted=opp.accepted_at is not None, expired=c["expired"],
    ))


@router.post("/proposals/{token}/accept")
def proposal_accept(token: str, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings)):
    opp = _opp_by_token(db, token)
    if opp is None:
        return _html(pg.gone_page("Proposta nao encontrada."), 404)
    result = crm_ops.accept_proposal(db, settings, opp)
    db.commit()
    if result == "expired":
        return _html(pg.gone_page("Esta proposta expirou. Fale com a equipe."), 410)
    return _html(pg.page("Aceite registrado", "<h1>Proposta aceita!</h1><p>Voce vai receber os proximos passos por aqui em instantes.</p>"))


def _briefing(db: Session, token: str) -> Briefing | None:
    return db.scalar(select(Briefing).where(Briefing.token == token))


@router.get("/briefing/{token}")
def briefing_form(token: str, db: Session = Depends(get_db)):
    b = _briefing(db, token)
    if b is None:
        return _html(pg.gone_page(), 404)
    return _html(pg.briefing_page(token, done=b.status == "submitted"))


@router.post("/briefing/{token}")
async def briefing_submit(token: str, request: Request, db: Session = Depends(get_db)):
    b = _briefing(db, token)
    if b is None:
        return _html(pg.gone_page(), 404)
    if b.status != "submitted":
        form = await _form(request)
        data = {k: sanitize_input(form.get(k, ""), 200) for k, _, _ in pg.BRIEFING_FIELDS}
        data["descricao"] = sanitize_input(form.get("descricao", ""), 1000)
        data["servicos"] = [sanitize_input(x, 100) for x in form.get("servicos", "").splitlines() if x.strip()][:12]
        b.data, b.status, b.submitted_at = data, "submitted", datetime.now(UTC)
        notify_human(db, f"briefing-{b.id}", "Briefing recebido: gere a previa do site.", kind="briefing_submitted",
                     opportunity_id=str(b.opportunity_id))
        db.commit()
    return _html(pg.briefing_page(token, done=True))


def _preview(db: Session, token: str) -> Preview | None:
    p = db.scalar(select(Preview).where(Preview.token == token))
    if p is None or p.status != "active" or aware(p.expires_at) < datetime.now(UTC):
        return None
    return p


@router.get("/preview/{token}")
def preview_page(token: str, db: Session = Depends(get_db)):
    p = _preview(db, token)
    if p is None:
        return _html(pg.gone_page("Esta previa expirou."), 410)
    link = f'<p style="text-align:center;padding:12px"><a href="/public/preview/{pg.e(token)}/feedback">Enviar feedback sobre esta previa</a></p>'
    csp = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'",
           "X-Robots-Tag": "noindex, nofollow"}
    return _html((p.html or "").replace("</body>", link + "</body>"), extra=csp)


@router.get("/preview/{token}/feedback")
def feedback_form(token: str, db: Session = Depends(get_db)):
    if _preview(db, token) is None:
        return _html(pg.gone_page("Esta previa expirou."), 410)
    return _html(pg.feedback_page(token))


@router.post("/preview/{token}/feedback")
async def feedback_submit(token: str, request: Request, db: Session = Depends(get_db)):
    p = _preview(db, token)
    if p is None:
        return _html(pg.gone_page("Esta previa expirou."), 410)
    form = await _form(request)
    comment = sanitize_input(form.get("comment", ""), 1000)
    if comment:
        p.feedback = [*(p.feedback or []), {"at": datetime.now(UTC).isoformat(), "comment": comment}]
        notify_human(db, f"preview-fb-{p.id}-{len(p.feedback)}", "Novo feedback do cliente sobre a previa.",
                     kind="preview_feedback", opportunity_id=str(p.opportunity_id))
        db.commit()
    return _html(pg.feedback_page(token, done=True))


@router.get("/nps/{token}")
def nps_form(token: str, db: Session = Depends(get_db)):
    opp = _opp_by_token(db, token)
    if opp is None:
        return _html(pg.gone_page(), 404)
    return _html(pg.nps_page(token, done=opp.nps_score is not None))


@router.post("/nps/{token}")
async def nps_submit(token: str, request: Request, db: Session = Depends(get_db)):
    opp = _opp_by_token(db, token)
    if opp is None:
        return _html(pg.gone_page(), 404)
    if opp.nps_score is None:
        form = await _form(request)
        try:
            score = max(0, min(10, int(form.get("score", ""))))
        except ValueError:
            raise HTTPException(422, "Nota invalida") from None
        opp.nps_score, opp.nps_comment = score, sanitize_input(form.get("comment", ""), 1000) or None
        if score <= 6:
            notify_human(db, f"nps-detractor-{opp.id}", f"NPS baixo ({score}). Entre em contato.", kind="nps_low",
                         opportunity_id=str(opp.id))
        db.commit()
    return _html(pg.nps_page(token, done=True))


