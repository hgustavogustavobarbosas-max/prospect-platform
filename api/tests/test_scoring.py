from app.services.ai_scoring import AIError, GeminiClient, parse_response, public_features
from app.services.quota import estimate_input_tokens
from app.services.retry import retry
from app.services.scoring import (
    Features,
    apply_ai_adjustment,
    in_pilot,
    parse_pilot,
    score_features,
)

PILOT = parse_pilot("barbearia,estetica")


def feats(**kw):
    base = dict(segment="barbearia", has_phone=True, mobile_phone=True, website_status="none",
                rating=4.7, reviews=120, business_status="OPERATIONAL")
    base.update(kw)
    return Features(**base)


def test_best_case_is_tier_a_and_explained():
    r = score_features(feats(), pilot_segments=PILOT)
    assert r.score == 95 and r.tier == "A" and r.excluded is None
    assert r.breakdown["sem_site"] == 35 and "sem site proprio (+35)" in r.justification
    assert r.version == "v1"


def test_site_ok_outside_pilot_is_low():
    r = score_features(
        feats(website_status="site_ok", segment="oficina", reviews=5, rating=3.0, mobile_phone=False),
        pilot_segments=PILOT,
    )
    assert r.tier == "C" and r.score == 0 and r.breakdown["segmento_fora_piloto"] == -10


def test_social_only_is_strong_signal():
    r = score_features(feats(website_status="social", reviews=40), pilot_segments=PILOT)
    assert r.breakdown["so_rede_social"] == 30 and r.tier == "A"


def test_exclusions():
    s = score_features(feats(suppressed=True), pilot_segments=PILOT)
    assert s.excluded == "suprimido" and s.score == 0
    c = score_features(feats(business_status="CLOSED_PERMANENTLY"), pilot_segments=PILOT)
    assert c.excluded == "fechado"


def test_segment_matching_ignores_accents_and_uses_substring():
    assert in_pilot("Clínica de Estética", PILOT)
    assert not in_pilot("Pet shop", PILOT)
    assert not in_pilot(None, PILOT)


def test_ai_adjustment_is_clamped_and_changes_tier_only_within_band():
    base = score_features(feats(website_status="site_ok", reviews=40, rating=4.4), pilot_segments=PILOT)
    ai = parse_response('{"adjustment": 99, "note": "perfil forte"}', tokens=120)
    assert ai.adjustment == 10 and ai.tokens == 120
    out = apply_ai_adjustment(base, ai.adjustment, ai.note)
    assert out.score == base.score + 10 and out.breakdown["ia_ajuste"] == 10
    assert "perfil forte" in out.justification


def test_ai_parse_rejects_garbage_and_cleans_note():
    for bad in ["sem json", '{"adjustment": "abc"}', '{"nota": 1}', ""]:
        try:
            parse_response(bad)
        except AIError:
            continue
        raise AssertionError(f"deveria falhar: {bad!r}")
    ok = parse_response('texto {"adjustment": -3, "note": "a\\nb\\u0000c"} fim')
    assert ok.adjustment == -3 and "\n" not in ok.note and "\x00" not in ok.note


def test_ai_receives_only_categories():
    f = public_features("barbearia", "Santana de Parnaiba", "none", 4.7, 120, True, 80)
    assert set(f) == {"segmento", "regiao", "site", "avaliacoes", "nota", "celular", "score_base"}
    assert f["avaliacoes"] == "muitas" and f["nota"] == "alta"


class _LLMResponse:
    def __init__(self, body, status_code=200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._body


class _LLMHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return self.responses.pop(0)


def test_gemini_client_maps_function_calls_and_results():
    http = _LLMHttp([_LLMResponse({
        "candidates": [{"content": {"parts": [{"functionCall": {
            "id": "call-1", "name": "get_plans", "args": {},
        }}]}}],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3},
    })])
    client = GeminiClient("api-key-not-printed", "gemini-2.5-flash", http=http)
    reserved = []
    result = client.chat(
        system="system",
        messages=[{"role": "user", "content": "quais planos?"}],
        tools=[{"name": "get_plans", "description": "lista planos", "input_schema": {"type": "object"}}],
        max_tokens=40,
        before_request=lambda: reserved.append("called"),
    )
    assert result.stop_reason == "tool_use" and result.tokens == 15
    assert result.blocks[0]["name"] == "get_plans" and result.blocks[0]["input"] == {}
    url, body, headers = http.calls[0]
    assert url.endswith("/gemini-2.5-flash:generateContent")
    assert headers == {"x-goog-api-key": "api-key-not-printed"}
    assert body["generationConfig"]["maxOutputTokens"] == 40
    assert reserved == ["called"]

    contents = client._contents([
        {"role": "assistant", "content": result.blocks},
        {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "call-1", "content": '{"plans": []}',
        }]},
    ], client._tool_names)
    assert contents[0]["parts"][0]["functionCall"]["name"] == "get_plans"
    assert contents[1]["parts"][0]["functionResponse"] == {
        "id": "call-1", "name": "get_plans", "response": {"plans": []},
    }


def test_gemini_adjust_and_retry_after_are_supported():
    http = _LLMHttp([
        _LLMResponse({}, 429, {"retry-after": "3"}),
        _LLMResponse({"candidates": [{"content": {"parts": [
            {"text": '{"adjustment": 4, "note": "bom"}'},
        ]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7}}),
    ])
    client = GeminiClient("key", "gemini-2.5-flash", http=http)
    sleeps = []
    attempts = iter([_TransientForTest(), "ok"])

    def call():
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    assert retry(call, attempts=2, base=0.1, sleep=sleeps.append) == "ok"
    assert sleeps == [3]
    result = client.adjust({"segmento": "barbearia"})
    assert (result.adjustment, result.tokens, result.note) == (4, 12, "bom")


def test_input_token_estimate_allows_prompt_under_configured_tpm():
    payload = {
        "system": "s" * 1800,
        "messages": [{"role": "user", "content": "Oi, quais planos vocês oferecem?"}],
        "tools": [{"name": "get_plans", "description": "lista"}],
    }
    assert estimate_input_tokens(payload) < 2_500


class _TransientForTest(Exception):
    retry_after = 3
