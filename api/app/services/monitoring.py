from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ApiUsage, Conversation, Interaction, OutboxEvent, Payment, Site, SuppressionEntry
from app.services.flags import get_flag


def summary(db: Session, settings: Settings) -> dict:
    now = datetime.now(UTC)
    today = now.date()

    def count(stmt):
        return db.scalar(stmt) or 0

    dead = count(select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "dead"))
    pending_old = count(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.status == "pending", OutboxEvent.created_at < now - timedelta(minutes=15),
            OutboxEvent.available_at <= now,
        )
    )
    stuck = count(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.status == "processing", OutboxEvent.updated_at < now - timedelta(minutes=30)
        )
    )
    handoffs = count(select(func.count(Conversation.id)).where(Conversation.status == "handoff"))
    week = now - timedelta(days=7)
    optouts = count(
        select(func.count(SuppressionEntry.id)).where(
            SuppressionEntry.reason == "opt_out", SuppressionEntry.created_at >= week
        )
    )
    outbound = count(
        select(func.count(Interaction.id)).where(Interaction.direction == "out", Interaction.created_at >= week)
    )
    usage = {
        u.provider: u for u in db.scalars(select(ApiUsage).where(ApiUsage.day == today)).all()
    }
    places_calls = usage["places"].calls if "places" in usage else 0
    llm_tokens = usage["llm"].tokens if "llm" in usage else 0
    sending = get_flag(db, "sending_enabled")
    optout_rate = round(optouts / outbound, 3) if outbound >= 20 else None

    from app.services.crm_ops import inbox

    sla = sum(1 for r in inbox(db, settings.human_sla_minutes) if r["sla_breached"])
    overdue = count(select(func.count(Payment.id)).where(Payment.status == "overdue"))
    sites_down = count(select(func.count(Site.id)).where(Site.status == "down"))

    alerts: list[dict] = []

    def alert(code, severity, message):
        alerts.append({"code": code, "severity": severity, "message": message})

    if dead:
        alert("outbox_dead", "critical", f"{dead} evento(s) no dead-letter do outbox.")
    if pending_old:
        alert("outbox_atrasado", "warning", f"{pending_old} evento(s) pendentes ha mais de 15 min.")
    if stuck:
        alert("outbox_travado", "warning", f"{stuck} evento(s) em processamento ha mais de 30 min.")
    if settings.places_daily_call_limit and places_calls >= 0.8 * settings.places_daily_call_limit:
        alert("quota_places", "warning", f"Places: {places_calls}/{settings.places_daily_call_limit} chamadas hoje.")
    if settings.llm_daily_token_limit and llm_tokens >= 0.8 * settings.llm_daily_token_limit:
        alert("quota_llm", "warning", f"LLM: {llm_tokens}/{settings.llm_daily_token_limit} tokens hoje.")
    if optout_rate is not None and optout_rate > 0.10:
        alert("optout_alto", "critical", f"Taxa de opt-out de {optout_rate:.0%} nos ultimos 7 dias.")
    if sla:
        alert("sla_humano", "warning", f"{sla} conversa(s) aguardando atendente alem do SLA de {settings.human_sla_minutes} min.")
    if overdue:
        alert("pagamentos_atrasados", "warning", f"{overdue} pagamento(s) em atraso.")
    if sites_down:
        alert("sites_fora_do_ar", "critical", f"{sites_down} site(s) de clientes fora do ar.")
    if not sending:
        alert("envios_pausados", "info", "Kill switch ativo: envios pausados.")

    return {
        "generated_at": now.isoformat(),
        "alerts": alerts,
        "metrics": {
            "outbox_dead": dead, "outbox_pending_old": pending_old, "outbox_stuck": stuck,
            "open_handoffs": handoffs, "optouts_7d": optouts, "outbound_7d": outbound,
            "optout_rate_7d": optout_rate, "places_calls_today": places_calls,
            "llm_tokens_today": llm_tokens, "sending_enabled": sending,
            "sla_breaches": sla, "payments_overdue": overdue, "sites_down": sites_down,
        },
    }
