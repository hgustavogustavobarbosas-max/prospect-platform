"""Lead Scoring Engine v1: regras deterministicas, auditaveis e versionadas (sem dependencias)."""

from dataclasses import dataclass, field

from app.services.normalize import normalize_text

SCORE_VERSION = "v1"

WEBSITE_RULES = {
    "none": ("sem_site", 35),
    "social": ("so_rede_social", 30),
    "site_down": ("site_fora_do_ar", 25),
    "unchecked": ("site_nao_verificado", 10),
    "site_ok": ("site_ok", 0),
}

LABELS = {
    "sem_site": "sem site proprio",
    "so_rede_social": "presenca apenas em rede social/agregador",
    "site_fora_do_ar": "site com erro ou fora do ar",
    "site_nao_verificado": "site nao verificado",
    "telefone_valido": "telefone valido",
    "telefone_celular": "celular (provavel WhatsApp)",
    "avaliacoes_100_mais": "100+ avaliacoes (negocio ativo)",
    "avaliacoes_30_mais": "30+ avaliacoes",
    "avaliacoes_10_mais": "10+ avaliacoes",
    "nota_alta": "nota alta (4.3+)",
    "nota_boa": "nota boa (4.0 a 4.2)",
    "nota_baixa": "nota baixa (<3.5)",
    "segmento_piloto": "segmento do piloto",
    "segmento_fora_piloto": "segmento fora do piloto",
    "ia_ajuste": "ajuste contextual da IA",
}

CLOSED = {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}


@dataclass(frozen=True)
class Features:
    segment: str | None
    has_phone: bool
    mobile_phone: bool
    website_status: str  # none|social|site_ok|site_down|unchecked
    rating: float | None = None
    reviews: int | None = None
    business_status: str | None = None
    suppressed: bool = False


@dataclass
class ScoreResult:
    score: int
    tier: str
    excluded: str | None
    breakdown: dict[str, int] = field(default_factory=dict)
    justification: str = ""
    version: str = SCORE_VERSION


def tier_for(score: int, tier_a: int = 70, tier_b: int = 40) -> str:
    return "A" if score >= tier_a else "B" if score >= tier_b else "C"


def in_pilot(segment: str | None, pilot: set[str]) -> bool:
    seg = normalize_text(segment)
    return bool(seg) and any(p and (p == seg or p in seg) for p in pilot)


def parse_pilot(raw: str) -> set[str]:
    return {normalize_text(x) for x in raw.split(",") if x.strip()}


def _justify(tier: str, score: int, breakdown: dict[str, int]) -> str:
    parts = [f"{LABELS.get(k, k)} ({v:+d})" for k, v in breakdown.items() if v != 0]
    return f"Lead {tier} ({score}/100): " + ("; ".join(parts) if parts else "sem sinais relevantes") + "."


def score_features(
    f: Features, *, pilot_segments: set[str], tier_a: int = 70, tier_b: int = 40
) -> ScoreResult:
    if f.suppressed:
        return ScoreResult(0, "C", "suprimido", {}, "Excluido: contato em lista de supressao.")
    if f.business_status in CLOSED:
        return ScoreResult(0, "C", "fechado", {}, "Excluido: estabelecimento fechado.")

    b: dict[str, int] = {}
    key, pts = WEBSITE_RULES.get(f.website_status, WEBSITE_RULES["unchecked"])
    b[key] = pts
    if f.has_phone:
        b["telefone_valido"] = 15
        if f.mobile_phone:
            b["telefone_celular"] = 10
    n = f.reviews or 0
    if n >= 100:
        b["avaliacoes_100_mais"] = 15
    elif n >= 30:
        b["avaliacoes_30_mais"] = 10
    elif n >= 10:
        b["avaliacoes_10_mais"] = 5
    if f.rating is not None:
        if f.rating >= 4.3:
            b["nota_alta"] = 10
        elif f.rating >= 4.0:
            b["nota_boa"] = 5
        elif f.rating < 3.5:
            b["nota_baixa"] = -5
    if in_pilot(f.segment, pilot_segments):
        b["segmento_piloto"] = 10
    else:
        b["segmento_fora_piloto"] = -10

    score = max(0, min(100, sum(b.values())))
    tier = tier_for(score, tier_a, tier_b)
    return ScoreResult(score, tier, None, b, _justify(tier, score, b))


def apply_ai_adjustment(
    r: ScoreResult, adjustment: int, note: str, *, tier_a: int = 70, tier_b: int = 40
) -> ScoreResult:
    """Soma o ajuste da IA (ja limitado a +-10) e recalcula tier e justificativa."""
    if r.excluded or adjustment == 0:
        return r
    b = {**r.breakdown, "ia_ajuste": adjustment}
    score = max(0, min(100, r.score + adjustment))
    tier = tier_for(score, tier_a, tier_b)
    text = _justify(tier, score, b)
    if note:
        text += f" Nota da IA: {note}"
    return ScoreResult(score, tier, None, b, text, r.version)
