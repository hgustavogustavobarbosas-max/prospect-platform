"""Orquestracao da prospeccao: ingestao de lugares, deduplicacao, scoring e retencao."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.config import Settings
from app.models import Business, Lead, ProspectingRun, SuppressionEntry
from app.services import audit
from app.services.ai_scoring import AIError, public_features
from app.services.lead_state import can_transition
from app.services.normalize import dedupe_key, is_mobile_br, normalize_phone_br
from app.services.places import PlaceDTO, PlacesClient, PlacesError
from app.services.quota import (
    QuotaExceeded,
    add_tokens,
    reserve_call,
    reserve_llm_request,
    tokens_available,
)
from app.services.scoring import (
    Features,
    ScoreResult,
    apply_ai_adjustment,
    parse_pilot,
    score_features,
)
from app.services.site_check import check_site, classify_url

log = structlog.get_logger()
SYSTEM = Principal("system:prospecting", "service")


class ProspectingError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class IngestStats:
    created: int = 0
    duplicates: int = 0


def placeholder_name(place_id: str) -> str:
    return f"[Places] {place_id[:12]}"


def place_hash(place_id: str) -> str:
    return hashlib.sha256(f"place:{place_id}".encode()).hexdigest()


def website_status(settings: Settings, website: str | None) -> str:
    kind = classify_url(website)
    if kind != "site":
        return kind  # none | social
    if not settings.site_check_enabled:
        return "unchecked"
    return check_site(website, timeout=settings.site_check_timeout)


def _score(
    db: Session, settings: Settings, llm, *, segment, region, place: PlaceDTO, ws: str, phone_e164
) -> ScoreResult:
    suppressed = bool(
        phone_e164
        and db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.identifier == phone_e164))
    )
    feats = Features(
        segment=segment, has_phone=bool(phone_e164), mobile_phone=is_mobile_br(phone_e164),
        website_status=ws, rating=place.rating, reviews=place.reviews,
        business_status=place.business_status, suppressed=suppressed,
    )
    result = score_features(
        feats, pilot_segments=parse_pilot(settings.pilot_segments),
        tier_a=settings.tier_a_min, tier_b=settings.tier_b_min,
    )
    if (
        llm is not None
        and not result.excluded
        and result.score >= settings.llm_min_base_score
        and tokens_available(db, "llm", settings.llm_daily_token_limit)
    ):
        try:
            features = public_features(
                segment, region, ws, place.rating, place.reviews, feats.mobile_phone, result.score
            )
            adj = llm.adjust(
                features,
                before_request=lambda payload: reserve_llm_request(db, settings, payload),
            )
            add_tokens(db, "llm", adj.tokens)
            result = apply_ai_adjustment(
                result, adj.adjustment, adj.note, tier_a=settings.tier_a_min, tier_b=settings.tier_b_min
            )
        except (AIError, QuotaExceeded) as exc:
            log.warning("ia_indisponivel_usando_score_deterministico", error=str(exc))
    return result


def apply_result(db: Session, lead: Lead, result: ScoreResult) -> None:
    lead.score, lead.tier = result.score, result.tier
    lead.score_version, lead.score_breakdown = result.version, result.breakdown
    lead.justification = result.justification
    target = None
    if result.excluded == "suprimido":
        target = "suppressed"
    elif result.excluded == "fechado":
        target = "lost"
    elif result.tier in ("A", "B"):
        target = "qualified"
    if target and lead.status != target and can_transition(lead.status, target):
        previous, lead.status = lead.status, target
        audit.record(db, SYSTEM, "transition", "leads", lead.id, {"from": previous, "to": target})
    audit.record(
        db, SYSTEM, "score", "leads", lead.id, {"version": result.version, "tier": result.tier}
    )


def ingest_place(
    db: Session, place: PlaceDTO, *, run: ProspectingRun, settings: Settings, llm
) -> str:
    """Retorna 'created' ou 'duplicate'. Nada alem do necessario e persistido (modo strict)."""
    if db.scalar(select(Business.id).where(Business.place_id == place.place_id)):
        return "duplicate"

    phone_e164 = normalize_phone_br(place.phone)
    ws = website_status(settings, place.website)
    permissive = settings.places_storage_mode == "permissive"

    if permissive:
        biz = Business(
            name=place.name or placeholder_name(place.place_id), place_id=place.place_id,
            segment=run.segment, region=run.region, address=place.address, phone=place.phone,
            phone_e164=phone_e164, website_url=place.website, has_website=ws not in ("none", "social"),
            source="google_places", website_status=ws, rating=place.rating,
            reviews_count=place.reviews, places_cached_at=datetime.now(UTC),
            dedupe_hash=dedupe_key(place.name, place.address, phone_e164, None)
            or place_hash(place.place_id),
        )
    else:
        biz = Business(
            name=placeholder_name(place.place_id), place_id=place.place_id,
            segment=run.segment, region=run.region, has_website=ws not in ("none", "social"),
            source="google_places", website_status=ws, dedupe_hash=place_hash(place.place_id),
        )
    try:
        with db.begin_nested():
            db.add(biz)
            db.flush()
    except IntegrityError:
        return "duplicate"

    lead = Lead(business_id=biz.id)
    db.add(lead)
    db.flush()
    result = _score(
        db, settings, llm, segment=run.segment, region=run.region, place=place, ws=ws,
        phone_e164=phone_e164,
    )
    apply_result(db, lead, result)
    return "created"


def run_pages(
    db: Session, run: ProspectingRun, client: PlacesClient, settings: Settings, llm, max_pages: int
) -> ProspectingRun:
    run.error = None
    stopped = False
    for _ in range(max_pages):
        try:
            reserve_call(
                db, "places", settings.places_daily_call_limit, settings.places_cost_micro_usd_per_call
            )
        except QuotaExceeded:
            run.status, stopped = "quota", True
            break
        try:
            places, token = client.search_text(
                run.text_query, page_size=run.page_size, page_token=run.next_page_token
            )
        except PlacesError as exc:
            run.status, run.error, stopped = "failed", str(exc)[:500], True
            db.commit()
            break
        stats = IngestStats()
        for place in places:
            if ingest_place(db, place, run=run, settings=settings, llm=llm) == "created":
                stats.created += 1
            else:
                stats.duplicates += 1
        run.pages += 1
        run.found += len(places)
        run.created += stats.created
        run.duplicates += stats.duplicates
        run.next_page_token = token
        db.commit()  # progresso persistido pagina a pagina (retomavel)
        if not token:
            break
    if not stopped:
        run.status = "partial" if run.next_page_token else "done"
    db.commit()
    return run


def fetch_live(db: Session, biz: Business, client: PlacesClient | None, settings: Settings) -> PlaceDTO:
    if biz.source != "google_places" or not biz.place_id:
        raise ProspectingError(422, "Negocio nao veio do Google Places")
    if client is None:
        raise ProspectingError(503, "GOOGLE_PLACES_API_KEY nao configurada")
    try:
        reserve_call(db, "places", settings.places_daily_call_limit, settings.places_cost_micro_usd_per_call)
    except QuotaExceeded:
        raise ProspectingError(429, "Quota diaria do Places esgotada") from None
    try:
        return client.get_place(biz.place_id)
    except PlacesError as exc:
        raise ProspectingError(502, str(exc)) from None


def rescore_lead(
    db: Session, lead: Lead, client: PlacesClient | None, settings: Settings, llm
) -> Lead:
    biz = db.get(Business, lead.business_id)
    if biz is None:
        raise ProspectingError(404, "Negocio do lead nao encontrado")
    if biz.source == "google_places":
        place = fetch_live(db, biz, client, settings)
        phone_e164 = normalize_phone_br(place.phone)
        ws = website_status(settings, place.website)
        if settings.places_storage_mode == "strict":
            biz.website_status = ws
    else:
        place = PlaceDTO(
            place_id=biz.place_id or "", rating=biz.rating, reviews=biz.reviews_count,
        )
        phone_e164 = biz.phone_e164
        ws = biz.website_status or classify_url(biz.website_url)
        if ws == "site":
            ws = website_status(settings, biz.website_url)
    result = _score(
        db, settings, llm, segment=biz.segment, region=biz.region, place=place, ws=ws,
        phone_e164=phone_e164,
    )
    apply_result(db, lead, result)
    db.commit()
    db.refresh(lead)
    return lead


def purge_expired(db: Session, settings: Settings) -> int:
    """Retencao do modo permissive: apaga campos do Places mais velhos que o TTL (mantem place_id)."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.places_cache_ttl_days)
    stmt = select(Business).where(
        Business.source == "google_places",
        Business.places_cached_at.is_not(None),
        Business.places_cached_at < cutoff,
    )
    rows = db.scalars(stmt).all()
    for b in rows:
        b.name = placeholder_name(b.place_id or "")
        b.address = b.phone = b.phone_e164 = b.website_url = None
        b.rating = b.reviews_count = b.places_cached_at = None
    db.commit()
    return len(rows)
